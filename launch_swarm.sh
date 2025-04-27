#!/bin/bash

RESULTS_PATH="results/results.csv"
mkdir -p "results"
> "$RESULTS_PATH"

SWARM_SIZE=30
PROPOSALS=("Go Left" "Go Right" "Stay Put" "Go Forward")

for (( i=1; i<=SWARM_SIZE; i++ ))
do
  PROPOSAL=${PROPOSALS[$((RANDOM % ${#PROPOSALS[@]}))]}
  ROBOT_ID="R$i"

  echo "Launching Robot $ROBOT_ID with proposal '$PROPOSAL'"

  python3 robot.py --robot-id "$ROBOT_ID" --proposal "$PROPOSAL" --swarm-size "$SWARM_SIZE" &
done

wait

echo "All robots have finished."
