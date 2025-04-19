import pika
import json
import argparse
from constants import (
    RMQ_HOST,
    RMQ_USER,
    RMQ_PASS
)

READINESS_QUEUE = 'readiness_queue'
START_EXCHANGE = 'start_voting_exchange'

ready_robots = set()
connection = None
channel = None
swarm_size = 0
start_signal_sent = False


def on_ready_message(ch, method, properties, body):
    global ready_robots, swarm_size, channel, start_signal_sent

    # Ignore possible delayed readiness signals
    if start_signal_sent:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    try:
        # Extract message data
        message = json.loads(body.decode())
        sender_id = message.get("robot_id")
        msg_type = message.get("type")

        # Process the readiness signal
        if sender_id is not None and msg_type == "ready":
            # Add robot to ready list
            if sender_id not in ready_robots:
                print(f"[->][Barrier] Received READY signal from '{sender_id}'")
                ready_robots.add(sender_id)
                print(f"[*][Barrier] Robots ready: {len(ready_robots)}/{swarm_size}")

            # All robots are ready
            if len(ready_robots) == swarm_size:
                print(f"[*][Barrier] All {swarm_size} robots ready. Broadcasting START signal")

                ch.exchange_declare(exchange=START_EXCHANGE, exchange_type="fanout", durable=True)
                start_message = json.dumps({"type": "start_voting"})
                ch.basic_publish(
                    exchange=START_EXCHANGE,
                    routing_key="",
                    body=start_message,
                    properties=pika.BasicProperties(
                        delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE
                    )
                )
                print(f"[<-][Barrier] START signal sent to exchange '{START_EXCHANGE}'")
                start_signal_sent = True

                print("[✓][Barrier] Stopping consumption...")
                ch.stop_consuming()
        else:
            print(f"[?][Barrier] Received malformed message: {message}")

        # Acknowledge the ready message after processing is done
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except json.JSONDecodeError:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        print(f"[x][Barrier] Error decoding JSON: {body.decode()}")
    except Exception as e:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        print(f"[x][Barrier] An unexpected error occurred: {e}")


def main(swarm_size_arg):
    global connection, channel, swarm_size, start_signal_sent

    swarm_size = swarm_size_arg
    # Ensure state variables are reset
    start_signal_sent = False
    ready_robots.clear()

    try:
        # Establish connection
        connection = pika.BlockingConnection(pika.ConnectionParameters(
            host=RMQ_HOST,
            credentials=pika.PlainCredentials(
                username=RMQ_USER,
                password=RMQ_PASS
            )
        ))
        channel = connection.channel()
        print("[*][Barrier] Connected to RabbitMQ")

        # Declare readiness signal queue
        channel.queue_declare(queue=READINESS_QUEUE, durable=True)
        print(f"[*][Barrier] Declared readiness queue '{READINESS_QUEUE}'")

        # Purge possible stale messages
        channel.queue_purge(queue=READINESS_QUEUE)

        # Process one READY signal at a time
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(
            queue=READINESS_QUEUE,
            on_message_callback=on_ready_message,
            auto_ack=False
        )

        # Start consuming messages
        channel.start_consuming()
    except pika.exceptions.AMQPConnectionError as e:
        print(f"[x][Barrier] Connection error: {e}")
    except KeyboardInterrupt:
        print("[!][Barrier] Shutting down...")
    except Exception as e:
         print(f"[x][Barrier] An unexpected error occurred: {e}")
    finally:
        if connection and connection.is_open:
            connection.close()
            print("[✓][Barrier] Barrier service stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-n', '--swarm-size',
        type=int,
        required=True
    )
    args = parser.parse_args()
    main(args.swarm_size)