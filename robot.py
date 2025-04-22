import pika
import json
import time
import uuid
import random
import collections
import argparse
import os
from constants import (
    RMQ_HOST,
    RMQ_USER,
    RMQ_PASS,
    EXCHANGE_NAME,
    POSSIBLE_PROPOSALS,
    RESULTS_DIR,
    RESULTS_FILENAME
)


class RobotVoter:
    def __init__(self, robot_id, proposal, swarm_size):
        self.robot_id = robot_id
        self.proposal = proposal
        self.swarm_size = swarm_size
        self.ready_robots = set()
        self.received_proposals = []
        self.connection = None
        self.channel = None
        self.queue_name = None
        self.final_decision = None
        self.start_time = None
        self.end_time = None
        print(f"Robot initialized\nID: {self.robot_id}\nProposal: {self.proposal}\nSwarm Size: {self.swarm_size}")


    def _on_ready(self, channel, method, properties, body):
        message = json.loads(body.decode())
        msg_type = message.get("type")
        sender_id = message.get("robot_id")

        if msg_type == "ready":
            if sender_id not in self.ready_robots:
                self.ready_robots.add(sender_id)
                print(f"[->][{self.robot_id}] Received READY from {sender_id} ({len(self.ready_robots)}/{self.swarm_size})")
        channel.basic_ack(delivery_tag=method.delivery_tag)

        if len(self.ready_robots) == self.swarm_size:
            print(f"[*][{self.robot_id}] All {self.swarm_size} robots reported ready.")
            channel.stop_consuming()


    def _on_message_callback(self, channel, method, properties, body):
        try:
            message = json.loads(body.decode())
            msg_type = message.get("type")
            sender_id = message.get("robot_id")

            if msg_type == "proposal":
                proposal = message.get("proposal")

                if proposal:
                    print(f"[->][{self.robot_id}] Received proposal '{proposal}' from {sender_id}")
                    self.received_proposals.append(proposal)
                else:
                    print(f"[?][{self.robot_id}] Received malformed message: {message}")

                if len(self.received_proposals) == self.swarm_size:
                    print(f"[*][{self.robot_id}] Received all {len(self.received_proposals)}/{self.swarm_size} expected proposals")
                    channel.stop_consuming()
            elif msg_type == "ready":
                print(f"[!][{self.robot_id}] Ignoring READY message from {sender_id} during proposal phase")
            else:
                print(f"[?][{self.robot_id}] Received malformed message: {message}")

            channel.basic_ack(delivery_tag=method.delivery_tag)
        except json.JSONDecodeError:
            channel.basic_ack(delivery_tag=method.delivery_tag)
            print(f"[x][{self.robot_id}] Error decoding JSON: {body.decode()}")
        except Exception as e:
            channel.basic_ack(delivery_tag=method.delivery_tag)
            print(f"[x][{self.robot_id}] An unexpected error occurred in callback: {e}")


    def _process_results(self):
        print(f"[*][{self.robot_id}] Processing collected proposals: {self.received_proposals}")
        if not self.received_proposals:
            print(f"[x][{self.robot_id}] No proposals received. Cannot determine decision")
            raise RuntimeError(f"[{self.robot_id}] No proposals received. Cannot determine decision")
        else:
            vote_counts = collections.Counter(self.received_proposals)
            print(f"[*][{self.robot_id}] Vote counts: {dict(vote_counts)}")

            max_votes = max(vote_counts.values())
            winners = [proposal for proposal, count in vote_counts.items() if count == max_votes]

            if len(winners) == 1:
                self.final_decision = winners[0]
                print(f"[✓][{self.robot_id}] Majority decision: {self.final_decision}")
            elif len(winners) > 1:
                winners.sort()
                self.final_decision = winners[0]
                print(f"[*][{self.robot_id}] Tie detected between: {winners}, applying fallback...")
                print(f"[✓][{self.robot_id}] Final decision after tie-break: {self.final_decision}")


    def run_vote(self):
        self.received_proposals = []

        try:
            self.connection = pika.BlockingConnection(pika.ConnectionParameters(
                host=RMQ_HOST,
                credentials=pika.PlainCredentials(
                    username=RMQ_USER,
                    password=RMQ_PASS
                )
            ))
            self.channel = self.connection.channel()
            print(f"[*][{self.robot_id}] Connected to RabbitMQ")

            self.channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="fanout", durable=True)
            print(f"[*][{self.robot_id}] Exchange '{EXCHANGE_NAME}' declared")

            queue = self.channel.queue_declare(queue="", exclusive=True)
            self.queue_name = queue.method.queue
            print(f"[*][{self.robot_id}] Declared exclusive queue: {self.queue_name}")
            self.channel.queue_bind(exchange=EXCHANGE_NAME, queue=self.queue_name)
            print(f"[*][{self.robot_id}] Queue '{self.queue_name}' bound to exchange '{EXCHANGE_NAME}'")

            ready_tag = self.channel.basic_consume(
                queue=self.queue_name,
                on_message_callback=self._on_ready,
                auto_ack=False
            )
            ready_msg = json.dumps({
                "type": "ready",
                "robot_id": self.robot_id
            })
            while len(self.ready_robots) < self.swarm_size:
                self.channel.basic_publish(
                    exchange=EXCHANGE_NAME,
                    routing_key="",
                    body=ready_msg
                )
                self.connection.process_data_events(time_limit=0.5)
                time.sleep(0.2)

            self.channel.basic_cancel(consumer_tag=ready_tag)
            print(f"[*][{self.robot_id}] All {self.swarm_size} robots ready")

            print(f"[*][{self.robot_id}] Exchanging proposals...")
            self.channel.basic_consume(
                queue=self.queue_name,
                on_message_callback=self._on_message_callback,
                auto_ack=False
            )
            proposal_message = json.dumps({
                "type": "proposal",
                "robot_id": self.robot_id,
                "proposal": self.proposal
            })
            self.channel.basic_publish(
                exchange=EXCHANGE_NAME,
                routing_key="",
                body=proposal_message,
                properties=pika.BasicProperties(
                    delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE
                )
            )
            print(f"[<-][{self.robot_id}] Published proposal: {proposal_message}")

            self.start_time = time.time()
            self.channel.start_consuming()
            self._process_results()
            self.end_time = time.time()
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[x][{self.robot_id}] Error connecting to {RMQ_HOST}: {e}")
        except KeyboardInterrupt:
            print(f"[!][{self.robot_id}] Shutting down...")
        except Exception as e:
            print(f"[x][{self.robot_id}] An unexpected error occurred: {e}")
        finally:
            if self.connection and self.connection.is_open:
                self.connection.close()
            results_path = os.path.join(RESULTS_DIR, RESULTS_FILENAME)
            try:
                with open(results_path, "a") as f:
                    f.write(f"{self.robot_id},{self.final_decision},{self.end_time - self.start_time:.4f}\n")
                    f.flush()
                print(f"--- Robot {self.robot_id} Finished. Appended results. ---")
            except IOError as e:
                print(f"[x][{self.robot_id}] Error writing results file {results_path}: {e}")



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-id", "--robot-id",
        type=str,
        default=f"robot_{uuid.uuid4()}"
    )
    parser.add_argument(
        "-p", "--proposal",
        type=str,
        default=random.choice(POSSIBLE_PROPOSALS),
        choices=POSSIBLE_PROPOSALS
    )
    parser.add_argument(
        "-n", "--swarm-size",
        type=int,
        required=True
    )

    args = parser.parse_args()

    robot = RobotVoter(
        robot_id=args.robot_id,
        proposal=args.proposal,
        swarm_size=args.swarm_size
    )

    os.makedirs(RESULTS_DIR, exist_ok=True)
    results_path = os.path.join(RESULTS_DIR, RESULTS_FILENAME)
    with open(results_path, "w") as f:
        f.write("")

    robot.run_vote()