import pika
import json
import time
import uuid
import random
import collections
import argparse
from constants import (
    RMQ_HOST,
    RMQ_USER,
    RMQ_PASS,
    EXCHANGE_NAME,
    POSSIBLE_PROPOSALS
)


class RobotVoter:
    def __init__(self, robot_id, proposal, swarm_size):
        self.robot_id = robot_id
        self.proposal = proposal
        self.swarm_size = swarm_size
        self.received_proposals = []
        self.connection = None
        self.channel = None
        self.queue_name = None
        self.final_decision = None
        print(f"Robot initialized\nID: {self.robot_id}\nProposal: {self.proposal}\nSwarm Size: {self.swarm_size}")


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
            print(f"[*][{self.robot_id}] Vote Counts: {dict(vote_counts)}")

            max_votes = max(vote_counts.values())
            winners = [proposal for proposal, count in vote_counts.items() if count == max_votes]

            if len(winners) == 1:
                self.final_decision = winners[0]
                print(f"[✓][{self.robot_id}] Majority Decision: {self.final_decision}")
            elif len(winners) > 1:
                winners.sort()
                self.final_decision = winners[0]
                print(f"[!][{self.robot_id}] Tie detected between: {winners}, applying fallback...")
                print(f"[✓][{self.robot_id}] Final Decision after tie-break: {self.final_decision}")

    
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

            print(f"[*][{self.robot_id}] Starting to consume messages...")
            self.channel.basic_consume(
                queue=self.queue_name,
                on_message_callback=self._on_message_callback,
                auto_ack=False
            )

            time.sleep(5)
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
            
            self.channel.start_consuming()

            self._process_results()
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[x][{self.robot_id}] Error connecting to {RMQ_HOST}: {e}")
        except KeyboardInterrupt:
            print(f"[!][{self.robot_id}] Shutting down...")
        except Exception as e:
            print(f"[x][{self.robot_id}] An unexpected error occurred: {e}")
        finally:
            if self.connection and self.connection.is_open:
                self.connection.close()
                print(f"[!][{self.robot_id}] Connection closed")
            print(f"--- Robot {self.robot_id} Finished ---")
            print(f"Final Decision: {self.final_decision}")


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
    robot.run_vote()