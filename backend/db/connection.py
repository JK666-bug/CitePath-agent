import os

import pymysql
from pymysql.cursors import DictCursor


def connect():
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "citepath_agent"),
        password=os.environ.get("MYSQL_PASSWORD", "citepath_agent"),
        database=os.environ.get("MYSQL_DATABASE", "citepath_agent"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        init_command="SET time_zone = '+08:00'",
    )
