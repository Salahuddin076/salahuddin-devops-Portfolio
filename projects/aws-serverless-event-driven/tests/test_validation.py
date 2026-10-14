import unittest

from helpers import valid_order

from validation import (
    is_valid_correlation_id,
    order_total_cents,
    validate_idempotency_key,
    validate_order,
)


def fields(errors):
    return [error.field for error in errors]


class ValidateOrderTests(unittest.TestCase):
    def test_valid_order_has_no_errors(self):
        self.assertEqual(validate_order(valid_order()), [])

    def test_non_object_body(self):
        self.assertEqual(fields(validate_order(["not", "an", "object"])), ["$"])
        self.assertEqual(fields(validate_order(None)), ["$"])

    def test_reports_every_problem_at_once(self):
        order = {"customerId": "bob", "currency": "JPY", "items": [], "coupon": "X"}
        self.assertEqual(fields(validate_order(order)), ["coupon", "customerId", "currency", "items"])

    def test_unknown_item_field_rejected(self):
        order = valid_order(items=[{"sku": "MUG-01", "quantity": 1, "unitPriceCents": 900, "discount": 5}])
        self.assertEqual(fields(validate_order(order)), ["items[0].discount"])

    def test_boolean_is_not_an_integer(self):
        order = valid_order(items=[{"sku": "MUG-01", "quantity": True, "unitPriceCents": 900}])
        self.assertEqual(fields(validate_order(order)), ["items[0].quantity"])

    def test_quantity_and_price_bounds(self):
        order = valid_order(
            items=[
                {"sku": "MUG-01", "quantity": 0, "unitPriceCents": 900},
                {"sku": "MUG-02", "quantity": 101, "unitPriceCents": -1},
                {"sku": "MUG-03", "quantity": 100, "unitPriceCents": 1_000_000},
            ]
        )
        self.assertEqual(
            fields(validate_order(order)),
            ["items[0].quantity", "items[1].quantity", "items[1].unitPriceCents"],
        )

    def test_float_price_rejected(self):
        order = valid_order(items=[{"sku": "MUG-01", "quantity": 1, "unitPriceCents": 9.99}])
        self.assertEqual(fields(validate_order(order)), ["items[0].unitPriceCents"])

    def test_bad_sku_and_non_object_item(self):
        order = valid_order(items=[{"sku": "lower", "quantity": 1, "unitPriceCents": 1}, "MUG-01"])
        self.assertEqual(fields(validate_order(order)), ["items[0].sku", "items[1]"])

    def test_duplicate_sku_rejected(self):
        item = {"sku": "MUG-01", "quantity": 1, "unitPriceCents": 900}
        errors = validate_order(valid_order(items=[item, dict(item)]))
        self.assertEqual(len(errors), 1)
        self.assertIn("duplicate sku MUG-01", errors[0].message)

    def test_too_many_items(self):
        items = [{"sku": f"SKU-{n}", "quantity": 1, "unitPriceCents": 1} for n in range(51)]
        self.assertEqual(fields(validate_order(valid_order(items=items))), ["items"])

    def test_total(self):
        self.assertEqual(order_total_cents(valid_order()), 2 * 1500 + 900)


class HeaderValidationTests(unittest.TestCase):
    def test_missing_or_empty_key(self):
        self.assertEqual(validate_idempotency_key(None)[0].message, "header is required")
        self.assertEqual(validate_idempotency_key("")[0].message, "header is required")

    def test_key_format(self):
        self.assertIn("8-128 characters", validate_idempotency_key("short")[0].message)
        self.assertEqual(len(validate_idempotency_key("has space 123")), 1)
        self.assertEqual(len(validate_idempotency_key("x" * 129)), 1)
        self.assertEqual(validate_idempotency_key("8f14e45f-ceea-467a-9575-0a1b2c3d4e5f"), [])

    def test_correlation_id_constraints(self):
        self.assertTrue(is_valid_correlation_id("req-123:abc"))
        self.assertFalse(is_valid_correlation_id(None))
        self.assertFalse(is_valid_correlation_id(""))
        self.assertFalse(is_valid_correlation_id("line\nbreak"))
        self.assertFalse(is_valid_correlation_id("x" * 129))


if __name__ == "__main__":
    unittest.main()
