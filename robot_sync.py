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
    POSSIBLE_PROPOSALS
)


READINESS_QUEUE = 'readiness_queue'
START_EXCHANGE = 'start_voting_exchange'
PROPOSAL_EXCHANGE = 'proposal_exchange'


class RobotVoter:
    def __init__(self, robot_id, proposal, swarm_size):
        # Swarm attributes
        self.robot_id = robot_id
        self.proposal = proposal
        self.swarm_size = swarm_size
        # State variables
        self.received_proposals = []
        self.connection = None
        self.channel = None
        self.start_signal_received = False
        self.proposal_queue_name = None
        self.final_decision = None
        print(f"Robot initialized\nID: {self.robot_id}\nProposal: {self.proposal}\nSwarm Size: {self.swarm_size}")


    def _on_start_signal_callback(self, channel, method, properties, body):
        try:
            # Extract message data
            message = json.loads(body.decode())
            msg_type = message.get("type")

            # Process the start signal
            if msg_type == "start_voting":
                print(f"[*][{self.robot_id}] Received START signal from barrier")
                self.start_signal_received = True
                channel.stop_consuming()
            else:
                print(f"[?][{self.robot_id}] Received malformed message: {msg_type}")

            # Acknowledge the start message after processing is done
            channel.basic_ack(delivery_tag=method.delivery_tag)
        except json.JSONDecodeError:
            channel.basic_ack(delivery_tag=method.delivery_tag)
            print(f"[x][{self.robot_id}] Error decoding JSON: {body.decode()}")
        except Exception as e:
            channel.basic_ack(delivery_tag=method.delivery_tag)
            print(f"[x][{self.robot_id}] An unexpected error occurred: {e}")


    def _on_proposal_message_callback(self, channel, method, properties, body):
        try:
            # Extract message data
            message = json.loads(body.decode())
            msg_type = message.get("type")
            sender_id = message.get("robot_id")

            # Process the proposal message
            if sender_id is not None and msg_type == "proposal":
                proposal = message.get("proposal")
                if proposal is not None and len(self.received_proposals) < self.swarm_size:
                    print(f"[->][{self.robot_id}] Received proposal '{proposal}' from {sender_id} ({len(self.received_proposals)+1}/{self.swarm_size})")
                    self.received_proposals.append(proposal)

                # Check if we have collected all proposals
                if len(self.received_proposals) == self.swarm_size:
                    print(f"[*][{self.robot_id}] Received all {len(self.received_proposals)}/{self.swarm_size} proposals")
                    channel.stop_consuming()
            else:
                print(f"[?][{self.robot_id}] Received non-proposal message: {message}")

            # Acknowledge the proposal message after processing is done
            channel.basic_ack(delivery_tag=method.delivery_tag)
        except json.JSONDecodeError:
            channel.basic_ack(delivery_tag=method.delivery_tag)
            print(f"[x][{self.robot_id}] Error decoding JSON: {body.decode()}")
        except Exception as e:
            channel.basic_ack(delivery_tag=method.delivery_tag)
            print(f"[x][{self.robot_id}] An unexpected error occurred: {e}")


    def _process_results(self):
        # Determine a winner
        print(f"[*][{self.robot_id}] Processing collected proposals: {self.received_proposals}")
        if not self.received_proposals or len(self.received_proposals) < self.swarm_size :
            print(f"[x][{self.robot_id}] Not enough proposals received. Cannot determine decision")
            raise RuntimeError(f"[{self.robot_id}] Not enough proposals received. Cannot determine decision")          
        else:
            vote_counts = collections.Counter(self.received_proposals)
            print(f"[*][{self.robot_id}] Vote counts: {dict(vote_counts)}")
            max_votes = max(vote_counts.values())
            winners = [p for p, c in vote_counts.items() if c == max_votes]
            if len(winners) == 1:
                self.final_decision = winners[0]
                print(f"[✓][{self.robot_id}] Majority Decision: {self.final_decision}")
            else:
                winners.sort()
                self.final_decision = winners[0]
                print(f"[!][{self.robot_id}] Tie detected between: {winners}, applying fallback...")
                print(f"[✓][{self.robot_id}] Final decision after tie-break: {self.final_decision}")


    def run_vote(self):
        # Ensure state variables are reset
        self.received_proposals = []
        self.start_signal_received = False
        self.final_decision = None

        try:
            # Establish connection
            self.connection = pika.BlockingConnection(pika.ConnectionParameters(
                host=RMQ_HOST,
                credentials=pika.PlainCredentials(
                    username=RMQ_USER,
                    password=RMQ_PASS
                )
            ))
            self.channel = self.connection.channel()
            print(f"[*][{self.robot_id}] Connected to RabbitMQ")

            # Declare start signal exchange and queue
            print(f"[*][{self.robot_id}] Waiting for START signal...")
            self.channel.exchange_declare(exchange=START_EXCHANGE, exchange_type="fanout", durable=True)
            start_queue = self.channel.queue_declare(queue="", exclusive=True)
            start_queue_name = start_queue.method.queue
            self.channel.queue_bind(exchange=START_EXCHANGE, queue=start_queue_name)
            print(f"[*][{self.robot_id}] Queue '{start_queue_name}' bound to start signal exchange '{START_EXCHANGE}'")

            # Setup consumer for start exchange
            self.channel.basic_consume(
                queue=start_queue_name,
                on_message_callback=self._on_start_signal_callback,
                auto_ack=False
            )

            # Declare rediness queue
            self.channel.queue_declare(queue=READINESS_QUEUE, durable=True)

            # Send readiness signal
            ready_message = json.dumps({"type": "ready", "robot_id": self.robot_id})
            self.channel.basic_publish(
                exchange="",
                routing_key=READINESS_QUEUE,
                body=ready_message,
                properties=pika.BasicProperties(
                    delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE
                )
            )
            print(f"[<-][{self.robot_id}] Published readiness signal to barrier")

            # Wait untill the start message is received
            print(f"[*][{self.robot_id}] Waiting for START signal from barrier...")
            self.channel.start_consuming()

            # Abort faulty voting round
            if not self.start_signal_received:
                print(f"[x][{self.robot_id}] Not enough proposals received. Cannot determine decision")
                raise RuntimeError(f"[{self.robot_id}] Not enough proposals received. Cannot determine decision")


            # Declare proposal exchange and queue
            print(f"[*][{self.robot_id}] Exchanging proposal...")
            self.channel.exchange_declare(exchange=PROPOSAL_EXCHANGE, exchange_type="fanout", durable=True)
            proposal_queue = self.channel.queue_declare(queue="", exclusive=True)
            self.proposal_queue_name = proposal_queue.method.queue
            self.channel.queue_bind(exchange=PROPOSAL_EXCHANGE, queue=self.proposal_queue_name)
            print(f"[*][{self.robot_id}] Bound to proposal exchange '{PROPOSAL_EXCHANGE}'")

            # Setup consumer for proposal messages
            self.channel.basic_consume(
                queue=self.proposal_queue_name,
                on_message_callback=self._on_proposal_message_callback,
                auto_ack=False
            )

            # Send proposal to proposal exchange
            proposal_message = json.dumps({
                "type": "proposal",
                "robot_id": self.robot_id,
                "proposal": self.proposal
            })
            self.channel.basic_publish(
                exchange=PROPOSAL_EXCHANGE,
                routing_key="",
                body=proposal_message,
                properties=pika.BasicProperties(
                    delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE
                )
            )
            print(f"[<-][{self.robot_id}] Published proposal")

            # Start consuming proposal messages
            print(f"[*][{self.robot_id}] Consuming proposal messages...")
            self.channel.start_consuming() # Blocks until N proposals confirmed

            # Process the proposals
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