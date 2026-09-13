"""The signing core.

A pin is relayed between instances that have never met, so the signature is the
only thing standing between a map and a map full of forged entries. These tests
are correspondingly blunt: mostly they check that verification FAILS when it
should.

Everything here is a plain function — no database, no Django — so the rules can be
tested exactly rather than through a view.
"""
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from inventory.community import (
    COORD_DECIMALS,
    PIN_VERSION,
    canonical_pin,
    generate_keypair,
    make_pin,
    public_from_private,
    sign,
    verify,
    verify_pin,
)


class KeypairTests(SimpleTestCase):
    def test_generates_two_64_char_hex_keys(self):
        private_hex, public_hex = generate_keypair()
        self.assertEqual(len(private_hex), 64)
        self.assertEqual(len(public_hex), 64)
        bytes.fromhex(private_hex)
        bytes.fromhex(public_hex)

    def test_every_instance_gets_a_different_keypair(self):
        a = generate_keypair()
        b = generate_keypair()
        self.assertNotEqual(a, b)

    def test_public_key_can_be_recovered_from_the_private_key(self):
        private_hex, public_hex = generate_keypair()
        self.assertEqual(public_from_private(private_hex), public_hex)


class SignVerifyTests(SimpleTestCase):
    def setUp(self):
        self.private_hex, self.public_hex = generate_keypair()

    def test_round_trip(self):
        sig = sign(self.private_hex, b"hello")
        self.assertTrue(verify(self.public_hex, b"hello", sig))

    def test_a_different_message_does_not_verify(self):
        sig = sign(self.private_hex, b"hello")
        self.assertFalse(verify(self.public_hex, b"goodbye", sig))

    def test_another_instances_key_does_not_verify(self):
        _, other_public = generate_keypair()
        sig = sign(self.private_hex, b"hello")
        self.assertFalse(verify(other_public, b"hello", sig))

    def test_a_tampered_signature_does_not_verify(self):
        sig = sign(self.private_hex, b"hello")
        flipped = ("0" if sig[0] != "0" else "1") + sig[1:]
        self.assertFalse(verify(self.public_hex, b"hello", flipped))

    def test_malformed_input_returns_false_rather_than_raising(self):
        """A remote instance sending junk is expected input, not a crash."""
        for bad_pub, bad_sig in [("", ""), ("zz", "zz"), ("00", "00"), ("NOTHEX", "NOTHEX")]:
            with self.subTest(public=bad_pub, signature=bad_sig):
                self.assertFalse(verify(bad_pub, b"hello", bad_sig))


class CanonicalPinTests(SimpleTestCase):
    def payload(self, **overrides):
        args = dict(
            public_key="ab" * 32,
            lat=51.5010,
            lon=-0.1416,
            country="GB",
            name="",
            updated_at="2026-09-13T12:00:00Z",
        )
        args.update(overrides)
        return canonical_pin(**args)

    def test_is_deterministic(self):
        self.assertEqual(self.payload(), self.payload())

    def test_key_order_in_the_caller_does_not_matter(self):
        """Keys are sorted, so the same pin always produces the same bytes."""
        a = canonical_pin(public_key="aa", lat=1.0, lon=2.0, updated_at="t")
        b = canonical_pin(updated_at="t", lon=2.0, lat=1.0, public_key="aa")
        self.assertEqual(a, b)

    def test_coordinates_are_encoded_as_strings_not_numbers(self):
        """Deliberate: floats can serialise differently across platforms and Python
        versions, and the signature covers these exact bytes. A JSON number would
        make verification fail for reasons that have nothing to do with tampering."""
        import json

        body = json.loads(self.payload())
        self.assertIsInstance(body["lat"], str)
        self.assertIsInstance(body["lon"], str)
        self.assertEqual(body["lat"], f"{51.5010:.{COORD_DECIMALS}f}")

    def test_every_signed_field_changes_the_bytes(self):
        """If a field were left out of the canonical payload, it could be altered in
        transit without invalidating the signature. This pins that each one counts."""
        base = self.payload()
        variants = {
            "public_key": self.payload(public_key="cd" * 32),
            "lat": self.payload(lat=51.5011),
            "lon": self.payload(lon=-0.1417),
            "country": self.payload(country="US"),
            "name": self.payload(name="Eric's workshop"),
            "updated_at": self.payload(updated_at="2026-09-14T12:00:00Z"),
        }
        for field, variant in variants.items():
            with self.subTest(field=field):
                self.assertNotEqual(base, variant, f"{field} is not covered by the signature")

    def test_pin_version_is_inside_the_signed_bytes(self):
        self.assertIn(f'"v":{PIN_VERSION}'.encode(), self.payload())

    def test_country_case_is_normalised(self):
        self.assertEqual(self.payload(country="gb"), self.payload(country="GB"))


class MakeAndVerifyPinTests(SimpleTestCase):
    def setUp(self):
        self.private_hex, self.public_hex = generate_keypair()
        self.pin = make_pin(
            self.private_hex,
            lat=51.5010,
            lon=-0.1416,
            country="GB",
            updated_at=datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc),
        )

    def test_a_pin_carries_its_own_verification_material(self):
        """Everything needed to check it is in the pin, which is what lets a relay
        verify what it forwards without holding anyone's secret."""
        for field in ("v", "public_key", "lat", "lon", "country", "updated_at", "signature"):
            self.assertIn(field, self.pin)

    def test_a_freshly_made_pin_verifies(self):
        self.assertTrue(verify_pin(self.pin))

    def test_timestamp_is_utc_iso(self):
        self.assertTrue(self.pin["updated_at"].endswith("Z"))

    def test_altering_any_signed_field_invalidates_the_pin(self):
        """The core security property. A relaying instance must not be able to nudge
        a pin somewhere else, or re-date it, or rename it."""
        for field, value in [
            ("lat", "51.6000"),
            ("lon", "-0.2000"),
            ("country", "FR"),
            ("name", "Someone else"),
            ("updated_at", "2030-01-01T00:00:00Z"),
            ("public_key", "ff" * 32),
            ("v", 99),
        ]:
            with self.subTest(field=field):
                tampered = dict(self.pin)
                tampered[field] = value
                self.assertFalse(verify_pin(tampered), f"tampering with {field} was not caught")

    def test_a_stripped_signature_does_not_verify(self):
        self.assertFalse(verify_pin({k: v for k, v in self.pin.items() if k != "signature"}))

    def test_a_pin_claiming_an_unknown_version_is_rejected(self):
        """A future or invented version must not be interpreted by guesswork."""
        for bad_version in (0, 2, 99, -1, "1", None):
            with self.subTest(v=bad_version):
                tampered = dict(self.pin)
                tampered["v"] = bad_version
                self.assertFalse(verify_pin(tampered))

    def test_the_version_is_inside_the_signed_bytes(self):
        """Regression. `v` was originally outside the signature, so a relay could
        relabel a pin in transit and it would still verify — the pin's own statement
        about its format was the one field nothing checked."""
        tampered = dict(self.pin)
        tampered["v"] = 2
        self.assertFalse(verify_pin(tampered))

    def test_a_correctly_signed_pin_from_a_future_version_is_still_rejected(self):
        """The version guard has to stand on its own. A genuine v2 pin — signed
        properly over v2 bytes — is still refused, because this build does not know
        what v2 means and must not pretend otherwise."""
        body = canonical_pin(
            public_key=self.public_hex,
            lat=self.pin["lat"],
            lon=self.pin["lon"],
            country="GB",
            name="",
            updated_at=self.pin["updated_at"],
            v=2,
        )
        future = dict(self.pin)
        future["v"] = 2
        future["signature"] = sign(self.private_hex, body)
        self.assertFalse(verify_pin(future))

    def test_a_stripped_field_does_not_verify(self):
        for field in ("public_key", "lat", "lon", "updated_at"):
            with self.subTest(field=field):
                self.assertFalse(verify_pin({k: v for k, v in self.pin.items() if k != field}))

    def test_a_pin_signed_by_a_different_key_but_claiming_this_public_key_fails(self):
        """The forgery case: attacker signs with their own key but writes the victim's
        public key into the pin. The signature will not match."""
        attacker_private, _ = generate_keypair()
        forged = dict(self.pin)
        forged["signature"] = sign(
            attacker_private,
            canonical_pin(
                public_key=self.pin["public_key"],
                lat=self.pin["lat"],
                lon=self.pin["lon"],
                country=self.pin["country"],
                name=self.pin["name"],
                updated_at=self.pin["updated_at"],
            ),
        )
        self.assertFalse(verify_pin(forged))

    def test_the_private_key_never_appears_in_a_pin(self):
        """A pin gets published to the whole network. Leaking the signing key there
        would let anyone forge this instance's pins forever."""
        for value in self.pin.values():
            self.assertNotIn(self.private_hex, str(value))

    def test_defaults_to_now_when_no_timestamp_is_given(self):
        pin = make_pin(self.private_hex, lat=1.0, lon=2.0)
        stamp = datetime.fromisoformat(pin["updated_at"].replace("Z", "+00:00"))
        self.assertLess(abs(datetime.now(timezone.utc) - stamp), timedelta(seconds=30))
        self.assertTrue(verify_pin(pin))

    def test_an_empty_name_is_fine_and_still_verifies(self):
        self.assertEqual(self.pin["name"], "")
        self.assertTrue(verify_pin(self.pin))

    def test_a_named_pin_verifies_and_keeps_the_name(self):
        pin = make_pin(self.private_hex, lat=1.0, lon=2.0, name="Dad's workshop")
        self.assertEqual(pin["name"], "Dad's workshop")
        self.assertTrue(verify_pin(pin))

    def test_negative_coordinates_round_trip(self):
        """Most of the UK is west of Greenwich, so this is the normal case, not an edge."""
        pin = make_pin(self.private_hex, lat=53.4833, lon=-2.2310, country="GB")
        self.assertEqual(pin["lon"], "-2.231000")
        self.assertTrue(verify_pin(pin))
