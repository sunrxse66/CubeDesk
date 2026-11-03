import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image
from cubedesk.pet import PetState, APPROACH, HOLD, RETURN, render_pet, play_pet


class PetTests(unittest.TestCase):
    def test_momo_has_a_distinct_curious_prowl_and_greeting_sequence(self):
        momo=PetState(now=0,character='momo');momo.request_call();momo.activate_pending(0)
        moti=PetState(now=0);moti.request_call();moti.activate_pending(0)
        self.assertEqual(momo.pose(.5)['phase'],'curious')
        self.assertEqual(moti.pose(.5)['phase'],'approaching')
        self.assertEqual(momo.pose(2)['phase'],'approaching')
        self.assertEqual(momo.pose(4)['phase'],'greeting')
        self.assertEqual(momo.pose(8)['phase'],'returning')
        self.assertEqual(momo.pose(11)['phase'],'idle')
        for instant in (0,.4,1.1,2,3.8,5.5,8.5,11):
            frame=momo.image(instant)
            self.assertEqual(frame.size,(240,240));self.assertEqual(frame.mode,'RGB')
        self.assertNotEqual(momo.image(5.5).tobytes(),moti.image(5.5).tobytes())

    def test_selecting_character_invalidates_frame_cache_and_pending_call(self):
        pet=PetState(now=0);old=pet.image(0).tobytes();pet.request_call()
        pet.select('momo',now=0)
        self.assertFalse(pet.pending)
        self.assertEqual(pet.status()['name'],'Момо')
        self.assertNotEqual(old,pet.image(0).tobytes())
        with self.assertRaises(ValueError):pet.select('unknown')
        self.assertEqual(pet.character,'momo')

    def test_repeated_momo_calls_do_not_restart_curiosity_and_return_is_continuous(self):
        pet=PetState(now=0,character='momo');pet.request_call();pet.activate_pending(0)
        pet.request_call();pet.activate_pending(.6)
        self.assertEqual(pet.called_at,0)
        before=pet.pose(8.5)['depth']
        pet.request_call();pet.activate_pending(8.5)
        self.assertAlmostEqual(pet.pose(8.5)['depth'],before)

    def test_complete_call_sequence_approaches_holds_and_returns(self):
        pet=PetState(now=0)
        self.assertEqual(pet.pose(0)['phase'],'idle')
        pet.request_call()
        # Previews or an offline connection must not consume the call.
        self.assertEqual(pet.pose(50)['phase'],'idle')
        self.assertTrue(pet.pending)
        pet.activate_pending(100)
        self.assertEqual(pet.pose(100)['depth'],0)
        self.assertAlmostEqual(pet.pose(100+APPROACH/2)['depth'],.5)
        self.assertEqual(pet.pose(100+APPROACH+.2)['phase'],'greeting')
        self.assertEqual(pet.pose(100+APPROACH+.2)['depth'],1)
        self.assertEqual(pet.pose(100+APPROACH+HOLD+.2)['phase'],'returning')
        self.assertEqual(pet.pose(100+APPROACH+HOLD+RETURN+.1)['phase'],'idle')
        self.assertEqual(pet.pose(100+APPROACH+HOLD+RETURN+.1)['depth'],0)

    def test_repeated_calls_do_not_restart_the_walk_or_jump_during_return(self):
        pet=PetState(now=0);pet.request_call();pet.activate_pending(0)
        before=pet.pose(1)['depth']
        pet.request_call();pet.activate_pending(1)
        self.assertEqual(pet.pose(1)['depth'],before)
        self.assertEqual(pet.called_at,0)
        now=APPROACH+HOLD+RETURN/2
        before=pet.pose(now)['depth']
        pet.request_call();pet.activate_pending(now)
        self.assertAlmostEqual(pet.pose(now)['depth'],before)
        self.assertEqual(pet.pose(now)['phase'],'approaching')

    def test_call_at_glass_extends_greeting(self):
        pet=PetState(now=0);pet.request_call();pet.activate_pending(0)
        pet.request_call();pet.activate_pending(APPROACH+HOLD-.1)
        self.assertEqual(pet.pose(APPROACH+HOLD+1)['phase'],'greeting')

    def test_rendered_poses_and_cached_frames(self):
        pet=PetState(now=0)
        idle=pet.image(0)
        pet.request_call();pet.activate_pending(0)
        near=pet.image(APPROACH+.2)
        self.assertEqual(idle.size,(240,240))
        self.assertEqual(near.mode,'RGB')
        self.assertNotEqual(idle.tobytes(),near.tobytes())
        self.assertEqual(pet.image(APPROACH+.2).tobytes(),near.tobytes())
        pet.reset();self.assertFalse(pet.pending)
        self.assertEqual(pet.pose(100)['phase'],'idle')

    def test_stream_consumes_queued_call_and_sends_negotiated_jpeg(self):
        stop=threading.Event();pet=PetState();pet.request_call();sent=[];closed=[]
        class Link:
            flags,max_jpeg=7,8192
            def __init__(self,*a,**kw):pass
            def send_jpeg(self,data):sent.append(data);stop.set();return {'transport_ms':10}
            def close(self):closed.append(True)
        with patch('cubedesk.pet.CubeConnection',Link):
            play_pet('unused','secret',pet,stop,report=lambda _:None)
        self.assertFalse(pet.pending)
        with Image.open(io.BytesIO(sent[0])) as frame:self.assertEqual(frame.size,(120,120))
        self.assertEqual(closed,[True])
