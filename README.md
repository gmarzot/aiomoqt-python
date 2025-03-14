# aiomoqt - Media over QUIC Transport (MoQT)

`aiomoqt` is an implementaion of the MoQT protocol, based on `aioquic` and `asyncio`.

## Overview

This package implements the [MoQT Specification](https://moq-wg.github.io/moq-transport/draft-ietf-moq-transport.html) (currently **draft-08**). It is desinged for general use as an MoQT client and server library, supporting both 'publish' and 'subscribe'. The architecture is based on [asyncio](https://pypi.org/project/asyncio/), and extends the [aioquic](https://pypi.org/project/aioquic/) protocol.

### Featurtes

- Async Context Manager support for session connection management.
- High-level API for control messages with default and custom response handlers.
- Support for asynchronous and synchronous calls using the `wait_response` flag.
- Low-level API for control and data message serialization and deserialization.

🚀 **Status:** Alpha

## Installation

Install using `pip`:

```bash
pip install aiomoqt
```

Or using `uv`:

```bash
uv pip install aiomoqt
```

## Usage

### Basic Client Example

```python
import asyncio
from aiomoqt.client import MOQTClientSession

    client = MOQTClientSession(host=127.0.0.1, port=443, endpoint='wt-endpoint')

    async with client.connect() as session:
        try:
            await session.client_session_init():
            response = await session.subscribe(
                'namespace', 
                'track_name',
                wait_response=True
            )
            # wait for session close, process data and control messages
            await session.async_closed()
        except MOQTException as e:
            session.close(e.error_code, e.reason_phrase)

asyncio.run(main())
```

For the control message API, those messages which require a response will support the asyncio 'await' call construct. These message API's may also be called non-blocking/asynchronously and the response will be handled by the default handler. (note: in the future they support a call-back completion function). The message serialization/deseriliation classes provide <moqt-msg-obj>.serialize() which returns an 'aioquic' Buffer with the entire message serialized in buf.data and buf.tell() at the end of the buffer. The buffer data may passed directly to send_control_message(). The <moqt-msg-class>.deserialize() call returns an instance of the given class populated from the deserialized data. These calls expect that for messages that start with a type and length, will already have had the type and length parsed/pulled provided 'aioquic' buffer.

#### see aiomoqt-python/aiomoqt/examples for additional examples

## Development

To set up a development environment:

```bash
git clone https://github.com/gmarzot/aiomoqt-python.git
cd aiomoqt-python
./bootstrap_python.sh
source .venv/bin/activate
```
## Installation

```bash
uv pip install .
```

## TODO

* FETCH/OK, Joining FETCH/OK, 
* Direct QUIC connection
* GOAWAY, SUBSCRIBE_UPDATE, ANNOUNCE (beyond the basic), etc.
* Move track data read/write API to aiomoqt.messages.track
* Support file I/O [MOQT File Format](https://datatracker.ietf.org/doc/html/draft-jennings-moq-file-00)
* More tests

## Contributing

Contributions are welcome! If you'd like to contribute, please:

* Fork the repository on GitHub.
* Create a new branch for your feature or bug fix.
* Submit a pull request with a clear description of your changes.

For major changes, please open an issue first to discuss your proposal.

## Resources

- [MoQT Specification](https://moq-wg.github.io/moq-transport/draft-ietf-moq-transport.html)
- [Media Over QUIC Working Group](https://datatracker.ietf.org/wg/moq/about/)
- [`aiomoqt` GitHub Repository](https://github.com/gmarzot/aiomoqt-python)

---

## Acknowledgements

This project takes inspiration from, and has benefited from the great work done by the [Meta/moxygen](https://github.com/facebookexperimental/moxygen) team, and the efforts of the MOQ IETF WG.

