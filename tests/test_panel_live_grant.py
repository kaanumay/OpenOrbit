"""Panel-only live management: no chat parser; grants are public, removals are audited and silent."""
from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import yonetim


class _Profile:
    def __init__(self, user_id=42, name='Regal'):
        self.user_id = user_id
        self.d = {'pilot': {'userName': name, 'credits': 5, 'uridium': 6, 'honourPoints': 7, 'ep': 8, 'level': 3},
                  'esyalar': {'101': 'equipment_weapon_laser_lf-1', '102': 'equipment_weapon_laser_lf-1',
                              '103': 'equipment_weapon_laser_lf-1'},
                  'cephane': {'ammunition_laser_lcb-10': 100, 'ammunition_laser_mcb-25': 0},
                  'madenler': [{'_': 'OreCountModule', 'oreType': {'_': 'OreTypeModule', 'typeValue': 0}, 'count': 40}],
                  'diger_esyalar': {'resource_x': 9},
                  'gemiler': {'1': {'lootId': 'ship_goliath'}}, 'aktif_gemi': '1', 'dronlar': []}
        self.lock = threading.RLock()
        self.dirty = False
        self.saved = False
        self.equipped = {101}

    def save(self):
        self.saved = True

    def equipped_ids(self):
        return set(self.equipped)

    def ammo(self, loot):
        return self.d['cephane'].get(loot, 0)

    def add_ammo(self, loot, n):
        self.d['cephane'][loot] = self.d['cephane'].get(loot, 0) + n
        return self.d['cephane'][loot]

    def menu_status(self, loot):
        return {'menuItemId': loot}

    def ore_count(self, t):
        return sum(m['count'] for m in self.d['madenler'] if m['oreType']['typeValue'] == t)

    def remove_ores(self, ores):
        for t, n in ores.items():
            for m in self.d['madenler']:
                if m['oreType']['typeValue'] == t:
                    m['count'] -= n

    def resource(self, loot):
        return self.d['diger_esyalar'].get(loot, 0)

    def add_resource(self, loot, n):
        self.d['diger_esyalar'][loot] = max(0, self.d['diger_esyalar'].get(loot, 0) + n)
        return self.d['diger_esyalar'][loot]


class _Shop:
    def __init__(self):
        self.calls = []

    def reward(self, loot, amount):
        self.calls.append((loot, amount))
        return [('LootCommand', {'loot': loot, 'amount': amount})]

    def money_msgs(self):
        return []

    def item_id(self, loot):
        return 900

    def inv_item(self, iid, loot, total):
        return ('InventoryItemUpdatedCommand', {'itemId': iid, 'amount': total})

    def hangar_item(self, iid, loot, total):
        return {'itemid': iid, 'itemCount': total}

    def pack(self, items):
        return ('InventoryItemPack', {'items': items})

    def ore_pack(self, types):
        return ('OrePack', {'types': types})

    def resource_msgs(self, loot, total, n):
        return [('ResourceCount', {'loot': loot, 'total': total, 'n': n})]


class _Session:
    def __init__(self, user_id=42, name='Regal'):
        self.profil = _Profile(user_id, name)
        self.magaza = _Shop()
        self.sent = []

    def send(self, messages, quiet=False):
        self.sent.append((messages, quiet))


class _Chat:
    def __init__(self):
        self.messages = []

    def duyuru(self, text):
        self.messages.append(text)


class _Game:
    def __init__(self, *sessions):
        self.session = sessions[0] if sessions else _Session()
        self.OTURUMLAR = list(sessions) or [self.session]
        self.SOHBET = _Chat()

    def log(self, text):
        pass


class _AuditedCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.audit_path = str(Path(tmp.name) / 'audit.log')
        patcher = patch.object(yonetim, 'AUDIT_PATH', self.audit_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        ores = patch.object(yonetim, '_ores', return_value={0: 'resource_ore_prometium'})
        ores.start()
        self.addCleanup(ores.stop)


class PanelLiveGrantTest(_AuditedCase):
    def test_grant_rewards_connected_player_and_announces_to_everyone(self):
        game = _Game()
        with patch.object(yonetim, 'known_loots', return_value={'ammunition_laser_lcb-10': 'ammunition'}):
            result = yonetim.grant(game, '42', 'ammunition_laser_lcb-10', 25)
        self.assertEqual(game.session.magaza.calls, [('ammunition_laser_lcb-10', 25)])
        self.assertTrue(game.session.profil.saved)
        self.assertEqual(game.session.sent[0][1], True)
        self.assertEqual(len(game.SOHBET.messages), 1)
        self.assertIn('Regal', game.SOHBET.messages[0])
        self.assertEqual(result['adet'], 25)
        self.assertEqual(yonetim.audit_entries()[0]['islem'], 'ver')

    def test_grant_rejects_unknown_loot_before_changing_a_profile(self):
        game = _Game()
        with patch.object(yonetim, 'known_loots', return_value=set()):
            with self.assertRaisesRegex(ValueError, 'Bilinmeyen eşya'):
                yonetim.grant(game, '42', 'not-a-real-item', 1)
        self.assertEqual(game.session.magaza.calls, [])
        self.assertFalse(game.session.profil.saved)

    def test_only_connected_player_ids_are_available(self):
        game = _Game()
        self.assertEqual(yonetim.players(game), [{'id': '42', 'ad': 'Regal'}])
        with patch.object(yonetim, 'known_loots', return_value={'ammunition_laser_lcb-10': 'ammunition'}):
            with self.assertRaisesRegex(ValueError, 'artık bağlı değil'):
                yonetim.grant(game, '999', 'ammunition_laser_lcb-10', 1)

    def test_grant_all_rewards_every_connected_player_with_one_announcement(self):
        a, b = _Session(1, 'Ada'), _Session(2, 'Bob')
        game = _Game(a, b)
        with patch.object(yonetim, 'known_loots', return_value={'ammunition_laser_lcb-10': 'ammunition'}):
            result = yonetim.grant_all(game, 'ammunition_laser_lcb-10', 5)
        self.assertEqual(a.magaza.calls, [('ammunition_laser_lcb-10', 5)])
        self.assertEqual(b.magaza.calls, [('ammunition_laser_lcb-10', 5)])
        self.assertTrue(a.profil.saved and b.profil.saved)
        self.assertEqual(len(game.SOHBET.messages), 1)
        self.assertEqual(sorted(result['oyuncular']), ['Ada', 'Bob'])

    def test_grant_all_needs_a_connected_player(self):
        game = _Game()
        game.OTURUMLAR = []
        with patch.object(yonetim, 'known_loots', return_value={'x'}):
            with self.assertRaisesRegex(ValueError, 'bağlı oyuncu yok'):
                yonetim.grant_all(game, 'x', 1)


class PanelInventoryRemovalTest(_AuditedCase):
    def test_inventory_lists_gear_ammo_ore_and_resources(self):
        game = _Game()
        env = yonetim.inventory(game, '42')
        rows = {(r['tur'], r['esya']): r for r in env['esyalar']}
        gear = rows[('ekipman', 'equipment_weapon_laser_lf-1')]
        self.assertEqual((gear['adet'], gear['takili'], gear['silinebilir']), (3, 1, 2))
        self.assertEqual(rows[('cephane', 'ammunition_laser_lcb-10')]['adet'], 100)
        self.assertNotIn(('cephane', 'ammunition_laser_mcb-25'), rows)
        self.assertEqual(rows[('cevher', 'resource_ore_prometium')]['adet'], 40)
        self.assertEqual(rows[('kaynak', 'resource_x')]['adet'], 9)
        self.assertEqual(rows[('gemi', 'ship_goliath')]['silinebilir'], 0)
        self.assertEqual(env['para']['kredi'], 5)

    def test_remove_ammo_updates_profile_client_and_audit_log_without_chat(self):
        game = _Game()
        result = yonetim.remove(game, '42', 'ammunition_laser_lcb-10', 30)
        self.assertEqual((result['once'], result['sonra']), (100, 70))
        self.assertEqual(game.session.profil.d['cephane']['ammunition_laser_lcb-10'], 70)
        self.assertTrue(game.session.profil.saved)
        names = [m[0] for m in game.session.sent[0][0]]
        self.assertIn('InventoryItemUpdatedCommand', names)
        self.assertEqual(game.SOHBET.messages, [])
        entry = yonetim.audit_entries()[0]
        self.assertEqual((entry['islem'], entry['oyuncu'], entry['esya'], entry['adet']), ('cikar', 'Regal', 'ammunition_laser_lcb-10', 30))

    def test_remove_refuses_more_than_owned_and_leaves_profile_alone(self):
        game = _Game()
        with self.assertRaisesRegex(ValueError, 'yalnız 100'):
            yonetim.remove(game, '42', 'ammunition_laser_lcb-10', 101)
        self.assertEqual(game.session.profil.d['cephane']['ammunition_laser_lcb-10'], 100)
        self.assertEqual(yonetim.audit_entries(), [])

    def test_remove_gear_never_takes_equipped_items(self):
        game = _Game()
        yonetim.remove(game, '42', 'equipment_weapon_laser_lf-1', 2)
        self.assertEqual(list(game.session.profil.d['esyalar']), ['101'])
        removed = [m for m in game.session.sent[0][0] if m[0] == 'InventoryItemRemovedCommand']
        self.assertEqual(sorted(m[1]['itemId'] for m in removed), [102, 103])
        with self.assertRaisesRegex(ValueError, 'takılı'):
            yonetim.remove(game, '42', 'equipment_weapon_laser_lf-1', 1)

    def test_remove_ore_and_resource(self):
        game = _Game()
        yonetim.remove(game, '42', 'resource_ore_prometium', 15)
        self.assertEqual(game.session.profil.ore_count(0), 25)
        yonetim.remove(game, '42', 'resource_x', 9)
        self.assertEqual(game.session.profil.resource('resource_x'), 0)

    def test_remove_rejects_items_the_player_does_not_have(self):
        game = _Game()
        with patch.object(yonetim, 'known_loots', return_value={'ammunition_laser_sab-50'}):
            with self.assertRaisesRegex(ValueError, 'bu eşya yok'):
                yonetim.remove(game, '42', 'ammunition_laser_sab-50', 1)
            with self.assertRaisesRegex(ValueError, 'Bilinmeyen eşya'):
                yonetim.remove(game, '42', 'nonsense', 1)

    def test_remove_error_carries_pattern_for_panel_translation(self):
        game = _Game()
        with self.assertRaises(yonetim.Hata) as caught:
            yonetim.remove(game, '42', 'ammunition_laser_lcb-10', 500)
        self.assertEqual(caught.exception.kalip, 'Oyuncuda yalnız %d adet var.')
        self.assertEqual(caught.exception.values, ['100'])


class PanelOwnerChannelTest(_AuditedCase):
    def _start(self, game):
        server = yonetim.start(game, 'panel-secret', port=0)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def test_owner_endpoint_rejects_requests_without_the_panel_secret(self):
        server = self._start(_Game())
        for path in ('/oyuncular', '/envanter?oyuncu=42', '/denetim'):
            with self.assertRaises(HTTPError) as caught:
                urlopen('http://127.0.0.1:%d%s' % (server.server_address[1], path), timeout=2)
            self.assertEqual(caught.exception.code, 403)

    def test_inventory_and_audit_endpoints_work_with_the_secret(self):
        from urllib.request import Request
        game = _Game()
        server = self._start(game)
        base = 'http://127.0.0.1:%d' % server.server_address[1]
        head = {'X-OpenOrbit-Owner': 'panel-secret'}
        with urlopen(Request(base + '/envanter?oyuncu=42', headers=head), timeout=2) as r:
            self.assertEqual(json.loads(r.read())['oyuncu'], 'Regal')
        req = Request(base + '/cikar', data=json.dumps({'oyuncu': '42', 'esya': 'resource_x', 'adet': 2}).encode(),
                      headers=dict(head, **{'Content-Type': 'application/json'}), method='POST')
        with urlopen(req, timeout=2) as r:
            self.assertEqual(json.loads(r.read())['sonra'], 7)
        with urlopen(Request(base + '/denetim', headers=head), timeout=2) as r:
            self.assertEqual(json.loads(r.read())['kayitlar'][0]['islem'], 'cikar')


if __name__ == '__main__':
    unittest.main()
