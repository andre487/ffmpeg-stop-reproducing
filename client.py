#!/usr/bin/env python3
from pprint import pprint

import click
import requests


@click.group()
def main():
    pass


@main.command()
def get_tasks():
    resp = requests.get('http://localhost:8080/task')
    resp.raise_for_status()
    pprint(resp.json())


@main.command()
@click.option('--yt-page-url', default='https://www.youtube.com/watch?v=nA9UZF-SZoQ')
@click.option('--rtmp-endpoint', default='rtmp://localhost:1935/live/app')
def start_task(yt_page_url, rtmp_endpoint):
    resp = requests.post('http://localhost:8080/task', data={
        'yt_page_url': yt_page_url,
        'rtmp_endpoint': rtmp_endpoint,
    })
    resp.raise_for_status()
    pprint(resp.json())


@main.command()
@click.option('--task-id', required=True)
def stop_task(task_id):
    resp = requests.delete('http://localhost:8080/task', data={'task_id': task_id})
    resp.raise_for_status()
    pprint(resp.json())


if __name__ == '__main__':
    main()
