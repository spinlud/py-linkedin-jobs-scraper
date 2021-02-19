import base64


def base64_from_bytes(data: bytes) -> str:
    """
    Return encoded base64 string from bytes
    :param data:
    :return: str
    """

    return str(base64.b64encode(data), 'utf-8')
