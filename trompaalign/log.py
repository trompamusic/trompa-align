import logging
from io import BytesIO

import msgpack
import fluent.handler

custom_format = {
    "host": "%(hostname)s",
    "where": "%(module)s.%(funcName)s",
    "type": "%(levelname)s",
    "stack_trace": "%(exc_text)s",
}


def overflow_handler(pendings):
    unpacker = msgpack.Unpacker(BytesIO(pendings))
    for unpacked in unpacker:
        print(unpacked)


logger = logging.getLogger("trompaalign")

handler = fluent.handler.FluentHandler(
    "app.follow", host="fluentd", port=24224, buffer_overflow_handler=overflow_handler
)
formatter = fluent.handler.FluentRecordFormatter(custom_format)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)
