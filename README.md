# FFMPEG stop reproducing

This is an example for [the question on SO](https://stackoverflow.com/questions/75495329/how-to-terminate-ffmpeg-running-from-python)

## How to launch

1. Setup virtual env:
    ```bash
    ./setup,sh && source .venv/bin/activate
    ```
2. Run RTMP server (in another terminal):
    ```bash
   ./run-rtmp-server.sh
    ```
3. Run server:
   ```bash
   ./server.py
   ```
4. Start task:
   ```bash
   ./client.py start-task [--yt-page-url <YouTube stream page URL>] [--rtmp-endpoint <RTMP Endpoint URL>]
   ```
5. Stop task:
   ```bash
   ./client.py stop-task --task-id <Task ID from start-task>
   ```
6. Stop server
   ```
   Crtl + C
   ```
   
## The issue

If you stop a task by calling `./client.py stop-task` – ot stops. 
But when you stop server by `Ctrl + C` – it doesn't stop.
