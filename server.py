#!/usr/bin/env python3
import logging
import signal
import subprocess
import sys
import time
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Process, Queue, get_logger
from threading import Thread

from tornado.concurrent import run_on_executor
from tornado.httpclient import AsyncHTTPClient
from tornado.ioloop import IOLoop
from tornado.web import Application, RequestHandler, HTTPError
from yt_dlp import YoutubeDL

LOG_FMT = '%(asctime)s\t%(levelname)s\t%(name)s\t%(message)s'


def main():
    logging.basicConfig(level=logging.INFO, format=LOG_FMT)

    streaming_worker = StreamingWorker()
    streaming_worker.start()

    web_server = WebServer(streaming_worker.incoming_queue)
    stopping = False

    def stop_service(sig_num, _stack_frame):
        nonlocal stopping
        if not stopping:
            web_server.stop()
            logging.info(f'Stopping services by signal {sig_num}')
            stopping = True
        else:
            logging.info('Stop is already in progress')

    signal.signal(signal.SIGINT, stop_service)
    web_server.start()

    streaming_worker.stop()
    streaming_worker.join()


class StreamingWorker:
    def __init__(self):
        self.incoming_queue = Queue()
        self._process = Process(target=self._run_main_process)

    def start(self):
        self._process.start()

    def stop(self):
        self.incoming_queue.put({'action': 'quite'})

    def join(self):
        self._process.join()

    def _run_main_process(self):
        self._setup_logger()
        self._setup_signals()
        self._init_task_vars()

        self._logger.info('Streaming worker is started')
        while True:
            msg = None
            if not self.incoming_queue.empty():
                msg = self.incoming_queue.get_nowait()
                self._logger.info(f'Got message: {msg}')

            if not msg:
                time.sleep(1)
                continue

            match msg['action']:
                case 'quite':
                    self._logger.info('Quite')
                    break
                case 'start':
                    if self._cur_task:
                        self._logger.error('There is an active task already')
                    else:
                        self._start_streaming(msg['task'])
                case 'stop':
                    if not self._cur_task:
                        self._logger.info('Nothing to stop')
                    elif self._cur_task['task_id'] != msg['task']['task_id']:
                        self._logger.warning('Task ids do not match')
                    else:
                        self._stop_ffmpeg()

        if self._cur_task:
            self._stop_ffmpeg()

    def _setup_logger(self):
        self._logger = get_logger()
        self._logger.setLevel(logging.INFO)
        log_handler = logging.StreamHandler(sys.stderr)
        log_handler.setFormatter(logging.Formatter(LOG_FMT))
        self._logger.addHandler(log_handler)

    def _setup_signals(self):
        def do_nothing(sig_num, _stack_frame):
            self._logger.debug(f'Do nothing by signal {sig_num}')

        signal.signal(signal.SIGINT, do_nothing)

    def _init_task_vars(self):
        self._cur_task = None
        self._ffmpeg_process = None
        self._streaming_thread = None

    def _start_streaming(self, task):
        self._cur_task = task

        playlist_url = f'http://localhost:8080/playlist?yt_page_url={urllib.parse.quote_plus(task["yt_page_url"])}'
        self._ffmpeg_process = subprocess.Popen((
            'ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-i', playlist_url, '-c:v', 'copy', '-c:a', 'copy', '-f', 'flv',
            task['rtmp_endpoint'],
        ), stdin=subprocess.PIPE)

        self._streaming_thread = Thread(target=self._run_ffmpeg)
        self._streaming_thread.start()

    def _run_ffmpeg(self):
        if not self._ffmpeg_process:
            self._logger.error('There is no FFMPEG process')
            return

        self._ffmpeg_process.wait()
        if self._ffmpeg_process.returncode:
            self._logger.error(f'FFMPEG exited with non-zero code: {self._ffmpeg_process.returncode}')

    def _stop_ffmpeg(self):
        if not self._ffmpeg_process or not self._streaming_thread:
            self._logger.error('There is no FFMPEG process or streaming thread')
            return

        self._logger.info('Stopping FFMPEG')
        self._ffmpeg_process.stdin.write('q'.encode('GBK'))
        self._ffmpeg_process.stdin.flush()

        self._streaming_thread.join()

        self._init_task_vars()
        self._logger.info('FFMPEG is stopped')


class WebServer:
    def __init__(self, worker_queue):
        self._app = Application(
            [
                (r'/task', TaskHandler),
                (r'/playlist', PlaylistHandler),
            ],
            worker_queue=worker_queue,
        )

    def start(self):
        self._app.listen(8080)
        logging.info('Web server starting')
        IOLoop.current().start()
        logging.info('Web server is stopped')

    def stop(self):
        IOLoop.current().add_callback_from_signal(self._stop_server)

    def _stop_server(self):
        IOLoop.current().stop()


class TaskHandler(RequestHandler):
    tasks = {}

    async def get(self):
        await self.finish(self.tasks)

    async def post(self):
        yt_page_url = self.get_body_argument('yt_page_url', '')
        if not yt_page_url:
            raise HTTPError(400, reason='You need pass `yt_page_url`')

        rtmp_endpoint = self.get_body_argument('rtmp_endpoint', '')
        if not rtmp_endpoint:
            raise HTTPError(400, reason='You need pass `rtmp_endpoint`')

        task_id = str(uuid.uuid4())
        task = self.tasks[task_id] = {'task_id': task_id, 'yt_page_url': yt_page_url, 'rtmp_endpoint': rtmp_endpoint}

        logging.info(f'Creating task {task_id}')
        self.settings['worker_queue'].put_nowait({'action': 'start', 'task': task})
        await self.finish({'new_task': task})

    async def delete(self):
        task_id = self.get_body_argument('task_id', '')
        if not task_id:
            raise HTTPError(400, reason='You need pass `task_id`')

        if not (task := self.tasks.get(task_id)):
            raise HTTPError(404)

        logging.info(f'stopping task {task_id}')
        self.settings['worker_queue'].put_nowait({'action': 'stop', 'task': task})
        self.tasks.pop(task_id)

        await self.finish({'task_to_stop': task})

    def data_received(self, chunk):
        pass


class PlaylistHandler(RequestHandler):
    playlists = {}
    http_client = AsyncHTTPClient()
    executor = ThreadPoolExecutor()

    async def get(self):
        page_url = self.get_query_argument('yt_page_url', '')
        if not page_url:
            raise HTTPError(400, reason='You should pass `page_url`')

        if not (playlist_url := self.playlists.get(page_url)):
            playlist_url = await self._get_playlist_url(page_url)

        try:
            playlist_content, content_type = await self._fetch_playlist(playlist_url)
        except HTTPError:
            playlist_url = await self._get_playlist_url(page_url)
            try:
                playlist_content, content_type = await self._fetch_playlist(playlist_url)
            except HTTPError as e:
                raise HTTPError(500, reason=str(e))

        self.set_header('Content-Type', content_type)
        await self.finish(playlist_content)
        logging.info(f'Playlist for {page_url} is sent')

    def data_received(self, chunk):
        pass

    @run_on_executor
    def _get_playlist_url(self, page_url):
        logging.info(f'Getting a new playlist URL for {page_url}')

        ydl = YoutubeDL(dict(skip_download=True))
        info_dict = ydl.extract_info(page_url, download=False)
        if not (playlist_url := info_dict.get('url')):
            raise HTTPError(500, reason='There is no URL')

        self.playlists[page_url] = playlist_url
        return playlist_url

    async def _fetch_playlist(self, playlist_url):
        resp = await self.http_client.fetch(playlist_url)
        return resp.body.decode('utf8'), resp.headers.get('Content-Type', 'text/html')


if __name__ == '__main__':
    main()
