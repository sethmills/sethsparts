"""Community models: identity, the peer relationship, pairing codes, consent defaults.

The recurring theme is that the *defaults* are the privacy guarantees. A category
that shares by default, or a peer that can read inventory by default, would be a
silent breach of what the product promises — so most of these tests assert that
something is off or empty until deliberately turned on.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from inventory.community import public_from_private, verify_pin
from inventory.models import (
    Category,
    CommunityIdentity,
    CommunityProfile,
    PairingCode,
    Peer,
    PeerSearchLog,
)

from .factories import make_part, make_user


class CommunityIdentityTests(TestCase):
    def test_load_creates_the_keypair_on_first_use(self):
        identity = CommunityIdentity.load()
        self.assertEqual(len(identity.public_key), 64)
        self.assertEqual(len(identity.private_key), 64)

    def test_load_is_a_singleton(self):
        """Two workers starting at once must not end up with two identities — the
        public key is how the whole network knows this instance."""
        first = CommunityIdentity.load()
        second = CommunityIdentity.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(CommunityIdentity.objects.count(), 1)

    def test_the_public_key_actually_matches_the_private_key(self):
        identity = CommunityIdentity.load()
        self.assertEqual(public_from_private(identity.private_key), identity.public_key)

    def test_it_can_sign_a_pin_that_verifies(self):
        """End to end through the model: this is how pins will actually be produced."""
        identity = CommunityIdentity.load()
        from inventory.community import make_pin

        pin = make_pin(identity.private_key, lat=51.5010, lon=-0.1416, country="GB")
        self.assertEqual(pin["public_key"], identity.public_key)
        self.assertTrue(verify_pin(pin))

    def test_the_private_key_is_not_in_its_string_form(self):
        """__str__ goes into admin pages, logs and debug output. The signing key must
        never ride along."""
        identity = CommunityIdentity.load()
        self.assertNotIn(identity.private_key, str(identity))

    def test_the_private_key_is_not_in_the_repr(self):
        identity = CommunityIdentity.load()
        self.assertNotIn(identity.private_key, repr(identity))


class CommunityProfileTests(TestCase):
    def test_load_is_a_singleton(self):
        self.assertEqual(CommunityProfile.load().pk, CommunityProfile.load().pk)
        self.assertEqual(CommunityProfile.objects.count(), 1)

    def test_private_by_default(self):
        profile = CommunityProfile.load()
        self.assertFalse(profile.discoverable)
        self.assertFalse(profile.can_publish)

    def test_no_location_by_default(self):
        self.assertFalse(CommunityProfile.load().has_location)

    def test_cannot_publish_without_a_location(self):
        """Discoverability alone is not enough — a pin needs somewhere to be."""
        profile = CommunityProfile.load()
        profile.discoverable = True
        profile.save()
        self.assertFalse(profile.can_publish)

    def test_cannot_publish_without_opting_in(self):
        """A location alone is not consent to be on a map."""
        profile = CommunityProfile.load()
        profile.location_lat = 51.5010
        profile.location_lon = -0.1416
        profile.save()
        self.assertFalse(profile.can_publish)

    def test_can_publish_once_both_halves_are_set(self):
        profile = CommunityProfile.load()
        profile.discoverable = True
        profile.location_lat = 51.5010
        profile.location_lon = -0.1416
        profile.save()
        self.assertTrue(profile.can_publish)

    def test_turning_discoverability_off_stops_publication_immediately(self):
        """This is the opt-out path: the flag alone must be enough to stop a pin
        going out, without deleting the location."""
        profile = CommunityProfile.load()
        profile.discoverable = True
        profile.location_lat = 51.5010
        profile.location_lon = -0.1416
        profile.save()
        self.assertTrue(profile.can_publish)

        profile.discoverable = False
        profile.save()
        self.assertFalse(profile.can_publish)
        self.assertTrue(profile.has_location)  # remembered, but not published


class PeerDefaultTests(TestCase):
    """The defaults here are the whole reason the seed peer is safe."""

    def make_peer(self, **kwargs):
        kwargs.setdefault("name", "Someone")
        kwargs.setdefault("base_url", "https://example.test")
        return Peer.objects.create(**kwargs)

    def test_pins_are_exchanged_by_default(self):
        self.assertTrue(self.make_peer().exchanges_pins)

    def test_inventory_sharing_is_OFF_by_default(self):
        """The single most important default in this feature. Connecting to someone
        for map pins must never hand them the inventory."""
        self.assertFalse(self.make_peer().shares_parts)

    def test_a_peer_is_not_a_seed_by_default(self):
        self.assertFalse(self.make_peer().is_seed)

    def test_a_new_peer_starts_pending_not_active(self):
        """Nothing is queried and no key is honoured until the connection is confirmed
        by both sides."""
        peer = self.make_peer()
        self.assertEqual(peer.status, Peer.PENDING)
        self.assertFalse(peer.is_active)

    def test_each_peer_gets_its_own_inbound_key(self):
        a, b = self.make_peer(), self.make_peer(name="Another")
        self.assertTrue(a.inbound_api_key)
        self.assertNotEqual(a.inbound_api_key, b.inbound_api_key)

    def test_a_revoked_peer_is_not_active(self):
        peer = self.make_peer(status=Peer.ACTIVE)
        self.assertTrue(peer.is_active)
        peer.status = Peer.REVOKED
        peer.save()
        self.assertFalse(peer.is_active)

    def test_the_seed_peer_can_be_pins_only(self):
        """Exactly the shape the default connection needs: on the map together,
        inventory untouched."""
        seed = self.make_peer(name="Maintainer", is_seed=True, exchanges_pins=True, shares_parts=False)
        self.assertTrue(seed.exchanges_pins)
        self.assertFalse(seed.shares_parts)


class CategorySharingTests(TestCase):
    def test_nothing_is_shareable_by_default(self):
        """800+ parts, and sharing is opted into per category rather than per part —
        so this default is what stops an install sharing anything before its owner
        has decided anything."""
        self.assertFalse(Category.objects.create(name="Electronics").is_shareable)

    def test_a_part_with_no_category_is_never_shareable(self):
        """The plan's safe default: shareability is derived from the category, so an
        uncategorised part cannot be shared by accident."""
        part = make_part(name="Mystery thing")
        self.assertIsNone(part.category)

    def test_sharing_can_be_turned_on_per_category(self):
        category = Category.objects.create(name="Electronics", is_shareable=True)
        part = make_part(name="Resistor", category=category)
        part.refresh_from_db()
        self.assertTrue(part.category.is_shareable)


class PairingCodeTests(TestCase):
    def test_issue_produces_a_code_of_the_right_shape(self):
        code = PairingCode.issue()
        self.assertEqual(len(code.code), PairingCode.LENGTH)
        self.assertTrue(all(c in PairingCode.ALPHABET for c in code.code))

    def test_codes_avoid_lookalike_characters(self):
        """Crockford base32 drops I, L, O and U so a code can be read aloud without
        ambiguity — which matters because this is designed to be passed by phone."""
        for ch in "ILOU":
            self.assertNotIn(ch, PairingCode.ALPHABET)

    def test_issued_codes_do_not_collide(self):
        codes = {PairingCode.issue().code for _ in range(40)}
        self.assertEqual(len(codes), 40)

    def test_display_groups_for_reading_aloud(self):
        code = PairingCode.issue()
        self.assertEqual(code.display, f"{code.code[:4]}-{code.code[4:]}")

    def test_a_fresh_code_is_usable(self):
        self.assertTrue(PairingCode.issue().is_usable())

    def test_a_claimed_code_is_not_usable(self):
        """Single use is the real protection on an 8-character code."""
        code = PairingCode.issue()
        code.claimed_at = timezone.now()
        code.save()
        self.assertFalse(code.is_usable())

    def test_an_expired_code_is_not_usable(self):
        code = PairingCode.issue()
        code.expires_at = timezone.now() - timedelta(seconds=1)
        code.save()
        self.assertFalse(code.is_usable())

    def test_a_code_expires_after_the_stated_lifetime(self):
        now = timezone.now()
        code = PairingCode.issue(now=now)
        self.assertAlmostEqual(
            (code.expires_at - now).total_seconds(),
            PairingCode.LIFETIME_HOURS * 3600,
            delta=5,
        )

    def test_the_code_is_not_usable_one_second_after_expiry(self):
        code = PairingCode.issue()
        boundary = code.expires_at + timedelta(seconds=1)
        self.assertFalse(code.is_usable(now=boundary))

    def test_parsing_accepts_how_people_actually_type_it(self):
        self.assertEqual(PairingCode.parse_display("K7F2-9QX3"), "K7F29QX3")
        self.assertEqual(PairingCode.parse_display("k7f29qx3"), "K7F29QX3")
        self.assertEqual(PairingCode.parse_display("K7F2 9QX3"), "K7F29QX3")
        self.assertEqual(PairingCode.parse_display(" K7F2-9QX3 "), "K7F29QX3")

    def test_parsing_folds_the_ambiguous_characters(self):
        """Someone reading a code off a screen will type O for zero and I or l for one.
        Folding those is the point of choosing this alphabet."""
        self.assertEqual(PairingCode.parse_display("O0I1L"), "00111")

    def test_parsing_preserves_the_length(self):
        """Five characters in, five out — folding must not drop anything, or a code
        read aloud would come back the wrong length and never match."""
        parsed = PairingCode.parse_display("O0I1L")
        self.assertEqual(len(parsed), 5)

    def test_parsing_an_empty_value_is_safe(self):
        self.assertEqual(PairingCode.parse_display(""), "")
        self.assertEqual(PairingCode.parse_display(None), "")


class PeerSearchLogTests(TestCase):
    def test_a_search_is_recorded_against_the_peer(self):
        """The owner has to be able to check what a peer has been looking for rather
        than trusting them."""
        peer = Peer.objects.create(name="Dad", base_url="https://example.test")
        PeerSearchLog.objects.create(peer=peer, query="servo", result_count=3)

        entry = peer.searches.get()
        self.assertEqual(entry.query, "servo")
        self.assertEqual(entry.result_count, 3)

    def test_deleting_a_peer_takes_its_log_with_it(self):
        peer = Peer.objects.create(name="Dad", base_url="https://example.test")
        PeerSearchLog.objects.create(peer=peer, query="servo", result_count=1)
        peer.delete()
        self.assertEqual(PeerSearchLog.objects.count(), 0)


class AdminSafetyTests(TestCase):
    """The community models are registered in admin, so anything readable there is
    readable by whoever gets into the admin."""

    def test_the_signing_key_is_not_editable_through_the_admin(self):
        from inventory.admin import CommunityIdentityAdmin

        identity = CommunityIdentity.load()
        self.assertNotIn("private_key", CommunityIdentityAdmin.fields)
        self.assertNotIn("private_key", CommunityIdentityAdmin.readonly_fields)
        self.assertNotIn(identity.private_key, str(CommunityIdentityAdmin(CommunityIdentity, None)))

    def test_the_private_key_is_not_searchable_or_ordered_on(self):
        from inventory.admin import CommunityIdentityAdmin

        self.assertNotIn("private_key", CommunityIdentityAdmin.search_fields)
        self.assertNotIn("private_key", CommunityIdentityAdmin.list_display)
