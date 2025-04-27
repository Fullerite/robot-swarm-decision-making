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
    # Initialize robot state
    def __init__(self, robot_id, proposal, swarm_size):
        self.robot_id = robot_id
        self.proposal = proposal
        self.swarm_size = swarm_size
        self.ready_robots = set()  # Track IDs of robots that signaled "ready"
        self.received_proposals = []  # Store proposals received from others
        self.connection = None
        self.channel = None
        self.queue_name = None  # Unique queue for this robot
        self.final_decision = None  # Store the outcome of the vote
        self.start_time = None  # Track start of proposal exchange phase
        self.end_time = None  # Track end of decision making
        print(f"Robot initialized\nID: {self.robot_id}\nProposal: {self.proposal}\nSwarm Size: {self.swarm_size}")

    # Callback for handling "ready" messages
    def _on_ready(self, channel, method, properties, body):
        message = json.loads(body.decode())
        msg_type = message.get("type")
        sender_id = message.get("robot_id")

        if msg_type == "ready":
            if sender_id not in self.ready_robots:
                self.ready_robots.add(sender_id)
                # Log progress of readiness check
                print(f"[->][{self.robot_id}] Received READY from {sender_id} ({len(self.ready_robots)}/{self.swarm_size})")
        
        # Acknowledge message processing
        channel.basic_ack(delivery_tag=method.delivery_tag)

        # Stop consuming "ready" messages once all robots are accounted for
        if len(self.ready_robots) == self.swarm_size:
            print(f"[*][{self.robot_id}] All {self.swarm_size} robots reported ready.")
            channel.stop_consuming()

    # Callback for handling "proposal" messages
    def _on_message_callback(self, channel, method, properties, body):
        try:
            message = json.loads(body.decode())
            msg_type = message.get("type")
            sender_id = message.get("robot_id")

            if msg_type == "proposal":
                proposal = message.get("proposal")

                if proposal:
                    # Log and store received proposal
                    print(f"[->][{self.robot_id}] Received proposal '{proposal}' from {sender_id}")
                    self.received_proposals.append(proposal)
                else:
                    print(f"[?][{self.robot_id}] Received malformed message: {message}")

                # Stop consuming proposals once all expected messages are received
                if len(self.received_proposals) == self.swarm_size:
                    print(f"[*][{self.robot_id}] Received all {len(self.received_proposals)}/{self.swarm_size} expected proposals")
                    channel.stop_consuming()
            elif msg_type == "ready":
                # Ignore late "ready" messages during proposal phase
                print(f"[!][{self.robot_id}] Ignoring READY message from {sender_id} during proposal phase")
            else:
                print(f"[?][{self.robot_id}] Received malformed message: {message}")

            # Acknowledge message processing
            channel.basic_ack(delivery_tag=method.delivery_tag)
        except json.JSONDecodeError:
            # Handle potential errors in message format
            channel.basic_ack(delivery_tag=method.delivery_tag) # Ack even if bad format to prevent requeue
            print(f"[x][{self.robot_id}] Error decoding JSON: {body.decode()}")
        except Exception as e:
            # Catch-all for other callback errors
            channel.basic_ack(delivery_tag=method.delivery_tag) # Ack to prevent requeue
            print(f"[x][{self.robot_id}] An unexpected error occurred in callback: {e}")

    # Process collected proposals to determine the final decision
    def _process_results(self):
        print(f"[*][{self.robot_id}] Processing collected proposals: {self.received_proposals}")
        if not self.received_proposals:
            # Handle case where no proposals were received
            print(f"[x][{self.robot_id}] No proposals received. Cannot determine decision")
            raise RuntimeError(f"[{self.robot_id}] No proposals received. Cannot determine decision")
        else:
            # Count votes for each proposal
            vote_counts = collections.Counter(self.received_proposals)
            print(f"[*][{self.robot_id}] Vote counts: {dict(vote_counts)}")

            # Find the highest vote count
            max_votes = max(vote_counts.values())
            # Identify all proposals that achieved the max vote count
            winners = [proposal for proposal, count in vote_counts.items() if count == max_votes]

            if len(winners) == 1:
                # Single winner, majority decision
                self.final_decision = winners[0]
                print(f"[✓][{self.robot_id}] Majority decision: {self.final_decision}")
            elif len(winners) > 1:
                # Tie detected, apply deterministic tie-breaking (alphabetical sort)
                winners.sort()
                self.final_decision = winners[0] # Choose the first alphabetically
                print(f"[*][{self.robot_id}] Tie detected between: {winners}, applying fallback...")
                print(f"[✓][{self.robot_id}] Final decision after tie-break: {self.final_decision}")

    # Main execution flow for a robot
    def run_vote(self):
        self.received_proposals = [] # Reset proposals list for this run

        try:
            # Establish connection to RabbitMQ
            self.connection = pika.BlockingConnection(pika.ConnectionParameters(
                host=RMQ_HOST,
                credentials=pika.PlainCredentials(
                    username=RMQ_USER,
                    password=RMQ_PASS
                )
            ))
            self.channel = self.connection.channel()
            print(f"[*][{self.robot_id}] Connected to RabbitMQ")

            # Declare the fanout exchange
            self.channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="fanout", durable=True)
            print(f"[*][{self.robot_id}] Exchange '{EXCHANGE_NAME}' declared")

            # Declare an exclusive queue for this robot
            queue = self.channel.queue_declare(queue="", exclusive=True)
            self.queue_name = queue.method.queue
            print(f"[*][{self.robot_id}] Declared exclusive queue: {self.queue_name}")
            # Bind the queue to the exchange to receive messages
            self.channel.queue_bind(exchange=EXCHANGE_NAME, queue=self.queue_name)
            print(f"[*][{self.robot_id}] Queue '{self.queue_name}' bound to exchange '{EXCHANGE_NAME}'")

            # === Readiness Synchronization Phase ===
            # Start consuming messages using the _on_ready callback
            ready_tag = self.channel.basic_consume(
                queue=self.queue_name,
                on_message_callback=self._on_ready,
                auto_ack=False  # For manual acknowledgements
            )
            # Prepare the "ready" message payload
            ready_msg = json.dumps({
                "type": "ready",
                "robot_id": self.robot_id
            })
            # Loop: publish "ready" and process incoming messages until all robots are ready
            while len(self.ready_robots) < self.swarm_size:
                self.channel.basic_publish(
                    exchange=EXCHANGE_NAME,
                    routing_key="", # Not needed for fanout exchange
                    body=ready_msg
                )
                # Allow time for message processing and potential network latency
                self.connection.process_data_events(time_limit=0.5)
                time.sleep(0.2)

            # Cancel the "ready" consumer once synchronization is complete
            self.channel.basic_cancel(consumer_tag=ready_tag)
            print(f"[*][{self.robot_id}] All {self.swarm_size} robots ready")

            # === Proposal Exchange Phase ===
            print(f"[*][{self.robot_id}] Exchanging proposals...")
            # Start consuming messages using the proposal callback
            self.channel.basic_consume(
                queue=self.queue_name,
                on_message_callback=self._on_message_callback,
                auto_ack=False  # For manual acknowledgements
            )
            # Prepare the "proposal" message payload
            proposal_message = json.dumps({
                "type": "proposal",
                "robot_id": self.robot_id,
                "proposal": self.proposal
            })
            # Publish this robot's proposal to the exchange
            self.channel.basic_publish(
                exchange=EXCHANGE_NAME,
                routing_key="",
                body=proposal_message,
                properties=pika.BasicProperties(
                    delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE  # Ensures messages survive broker restarts
                )
            )
            print(f"[<-][{self.robot_id}] Published proposal: {proposal_message}")

            # Record start time just before blocking consumption starts
            self.start_time = time.time()
            # Enter blocking loop to receive proposals (exits via stop_consuming in callback)
            self.channel.start_consuming()
            # Once consumption stops (all proposals received), process results
            self._process_results()
            # Record end time after decision is made
            self.end_time = time.time()
        except pika.exceptions.AMQPConnectionError as e:
            # Handle RabbitMQ connection issues
            print(f"[x][{self.robot_id}] Error connecting to {RMQ_HOST}: {e}")
        except KeyboardInterrupt:
            # Allow graceful shutdown via Ctrl+C
            print(f"[!][{self.robot_id}] Shutting down...")
        except Exception as e:
            # Catch unexpected errors during the run
            print(f"[x][{self.robot_id}] An unexpected error occurred: {e}")
        finally:
            # Ensure connection is closed if it was opened
            if self.connection and self.connection.is_open:
                self.connection.close()
            # Define path for results file
            results_path = os.path.join(RESULTS_DIR, RESULTS_FILENAME)
            try:
                # Append this robot's result to the CSV file
                with open(results_path, "a") as f:
                    # Calculate convergence time for this robot
                    convergence_time = self.end_time - self.start_time if self.start_time and self.end_time else 0
                    f.write(f"{self.robot_id},{self.final_decision},{convergence_time:.4f}\n")
                    f.flush() # Ensure data is written immediately
                print(f"--- Robot {self.robot_id} Finished. Appended results. ---")
            except IOError as e:
                # Handle errors writing to the results file
                print(f"[x][{self.robot_id}] Error writing results file {results_path}: {e}")


if __name__ == "__main__":
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-id", "--robot-id",
        type=str,
        default=f"robot_{uuid.uuid4()}", # Default to a unique ID
    )
    parser.add_argument(
        "-p", "--proposal",
        type=str,
        default=random.choice(POSSIBLE_PROPOSALS), # Default to a random proposal
        choices=POSSIBLE_PROPOSALS, # Restrict choices to predefined values
    )
    parser.add_argument(
        "-n", "--swarm-size",
        type=int,
        required=True, # Swarm size must be specified
    )

    # Parse the command-line arguments
    args = parser.parse_args()

    # Create a RobotVoter instance with the parsed arguments
    robot = RobotVoter(
        robot_id=args.robot_id,
        proposal=args.proposal,
        swarm_size=args.swarm_size
    )

    # Start the voting process for this robot
    robot.run_vote()