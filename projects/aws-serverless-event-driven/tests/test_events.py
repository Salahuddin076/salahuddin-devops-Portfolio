import json
import unittest

from helpers import START

from events import EVENT_SOURCE, ORDER_ACCEPTED, event_id_for, order_accepted_detail, to_put_events_entry


def sample_detail(**overrides):
    args = dict(
        order_id="ord_abc",
        customer_id="cus_demo0001",
        currency="USD",
        total_cents=3900,
        item_count=3,
        correlation_id="req-1",
        occurred_at=START,
    )
    args.update(overrides)
    return order_accepted_detail(**args)


class EventShapeTests(unittest.TestCase):
    def test_detail_shape(self):
        detail = sample_detail()
        self.assertEqual(set(detail), {"version", "id", "occurredAt", "data", "metadata"})
        self.assertEqual(detail["version"], "1")
        self.assertEqual(
            detail["data"],
            {"orderId": "ord_abc", "customerId": "cus_demo0001", "currency": "USD", "totalCents": 3900, "itemCount": 3},
        )
        self.assertEqual(detail["metadata"], {"correlationId": "req-1"})
        self.assertTrue(detail["occurredAt"].endswith("Z"))

    def test_event_id_is_deterministic_per_order(self):
        self.assertEqual(sample_detail()["id"], sample_detail(correlation_id="other")["id"])
        self.assertEqual(sample_detail()["id"], event_id_for("ord_abc"))
        self.assertNotEqual(event_id_for("ord_abc"), event_id_for("ord_def"))

    def test_put_events_entry(self):
        entry = to_put_events_entry(sample_detail(), bus_name="orders-bus")
        self.assertEqual(set(entry), {"Source", "DetailType", "Detail", "EventBusName"})
        self.assertEqual(entry["Source"], EVENT_SOURCE)
        self.assertEqual(entry["DetailType"], ORDER_ACCEPTED)
        self.assertEqual(entry["EventBusName"], "orders-bus")
        self.assertEqual(json.loads(entry["Detail"]), sample_detail())

    def test_detail_fits_eventbridge_entry_limit(self):
        # PutEvents caps an entry at 256 KB; this event is tiny by design.
        entry = to_put_events_entry(sample_detail(), bus_name="orders-bus")
        self.assertLess(len(json.dumps(entry).encode()), 1024)


if __name__ == "__main__":
    unittest.main()
