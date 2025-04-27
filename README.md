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

```shell
    ./launch_swarm.sh
```

Better to keep `SWARM_SIZE` less or equal $30$ to more reliability.

## 3. Results

Results will store in the `/results` folder. Check `results.csv` file.
