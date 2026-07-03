def get_zone(hr, max_hr):
    pct = hr / max_hr * 100
    if pct <= 70:
        return 1
    elif pct <= 80:
        return 2
    elif pct <= 87:
        return 3
    elif pct <= 93:
        return 4
    else:
        return 5


def get_band(hr, max_hr):
    zone = get_zone(hr, max_hr)
    return 'easy' if zone <= 2 else 'moderate' if zone == 3 else 'hard'
