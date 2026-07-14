import threading

_awaiting_weight: dict[int, bool] = {}
_awaiting_weight_lock = threading.Lock()


def clear_awaiting_weight(chat_id: int | None = None):
    with _awaiting_weight_lock:
        if chat_id is not None:
            _awaiting_weight.pop(chat_id, None)
        else:
            _awaiting_weight.clear()
