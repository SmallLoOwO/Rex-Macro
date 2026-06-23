from miningbot.events import EventLog

def test_log_event_records_type_and_meta():
    log = EventLog()
    log.log("RARE_FOUND", mineral="Spectral 4FA208", tier="Spectral")
    assert len(log.records) == 1
    rec = log.records[0]
    assert rec.type == "RARE_FOUND"
    assert rec.meta["mineral"] == "Spectral 4FA208"
    assert rec.timestamp > 0

def test_sinks_are_called():
    seen = []
    log = EventLog()
    log.add_sink(lambda rec: seen.append(rec.type))
    log.log("STUCK", reason="no progress")
    assert seen == ["STUCK"]
