"""Independent channel state; TelemetryStore owns synchronization."""


class EncoderChannels:
    PINS = ('PA0', 'PB7')

    def __init__(self):
        self.reset()

    def reset(self):
        self.diagnostic = False
        self.auxiliary = False
        self._channels = [dict(reading=None, seen_at=None, samples=0, valid_samples=0)
                          for _ in self.PINS]

    def consume(self, line, decoder, now):
        channel = 1
        tagged = line.startswith('#ENCODER,')
        auxiliary = line.startswith('#ENCODER_AUX,')
        if tagged or auxiliary:
            fields = line.split(',')
            if len(fields) != 9 or fields[1] != '1' or fields[2] not in ('1', '2'):
                return None
            channel = int(fields[2])
            if auxiliary and channel != 2:
                return None
            reading = decoder(','.join(fields[3:]))
        else:
            reading = decoder(line)
        if reading is None:
            return None
        slot = self._channels[channel - 1]
        slot.update(reading=reading, seen_at=now, samples=slot['samples'] + 1,
                    valid_samples=slot['valid_samples'] + int(reading['valid']))
        self.diagnostic = self.diagnostic or tagged
        self.auxiliary = self.auxiliary or auxiliary
        return channel, reading, tagged

    def snapshot(self, connected, now):
        result = []
        for index, slot in enumerate(self._channels):
            age = None if slot['seen_at'] is None else max(0, now - slot['seen_at'])
            signal = ('disconnected' if not connected else 'waiting' if age is None else
                      'stale' if age >= 1 else 'valid' if slot['reading']['valid'] else 'invalid')
            reading = dict(slot['reading']) if slot['reading'] else None
            if reading and signal != 'valid':
                reading.update(valid=False, angle_deg=None, velocity_rad_s=None, frequency_hz=None)
            result.append(dict(id=index + 1, pin=self.PINS[index], signal=signal, reading=reading,
                               age_ms=None if age is None else round(age * 1000),
                               samples=slot['samples'], valid_samples=slot['valid_samples']))
        return result
