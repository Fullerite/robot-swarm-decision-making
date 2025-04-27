# ROBOT SWARM DECISION MAKING SYSTEM

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

- Also you can manually test one specific robot:

```shell
    python3 robot.py --robot-id "TestBot" --proposal "Go Left" --swarm-size 5
```

Better to keep `SWARM_SIZE` less or equal $30$ to more reliability.

## 3. Results

Results will store in the `/results` folder. Check `results.csv` file.

## 4. Clean up

```shell
    docker-compose down
```