# ROBOT SWARM DECISION MAKING SYSTEM

This project simulates a swarm of autonomous robots communicating through RabbitMQ to reach a majority decision on a set of proposals like "Go Left", "Go Right", "Stay Put", and "Go Forward".

Each robot:

- Signals readiness,

- Shares its individual proposal,

- Collects proposals from the entire swarm,

- Determines the majority decision (with a tie-breaker fallback),

- Logs the result to a CSV file.

RabbitMQ is used as the message broker to enable communication between robots.

## 1. Install depencies

First initialize `.venv` folder to avoid confuse with system interpreter.

```shell
    python -m venv /.venv # init venv
    ./.venv/bin/activate # activate venv
```

Then install depencies to `.venv` folder.

```shell
    pip install -r requirements.txt # install depencies
```

## 2. Launch

### Linux

```shell
    docker-compose up -d
    chmod +x launch_swarm.sh
    ./launch_swarm.sh
```

### Windows

```cmd
    docker-compose up -d
    launch_swarm.bat
```

- Also, you can manually test two or more robots:

```shell
    python3 robot.py --robot-id "TestBot1" --proposal "Go Left" --swarm-size 2

    python3 robot.py --robot-id "TestBot2" --proposal "Go Right" --swarm-size 2
```

Better to keep `SWARM_SIZE` less or equal to $30$ for more reliability in terms of synchronization.

## 3. Results

Results will be stored in the `/results` folder. Check `results.csv` file.

## 4. Clean up

```shell
    docker-compose down
```
