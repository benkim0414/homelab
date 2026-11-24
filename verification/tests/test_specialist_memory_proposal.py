"""Offline proposal checks. Fixture image references are never deployed."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'hindsight/proposals/specialist-memory/check_proposal.py'

class ProposalTests(unittest.TestCase):
    def test_active_manifest_changes_block_baseline_claim(self):
        module=self.load()
        with patch.object(module,'baseline_matches',return_value=False):
            with self.assertRaises(ValueError):module.check()

    def load(self):
        self.assertTrue(SOURCE.is_file(),'review-only proposal checker is missing')
        spec=importlib.util.spec_from_file_location('specialist_proposal',SOURCE)
        assert spec and spec.loader
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_real_patch_is_excluded_and_preserves_active_configuration(self):
        module=self.load()
        result=module.check()
        self.assertEqual(result['status'],'DRAFT_BLOCKED')
        self.assertIs(result['deployable'],False)
        self.assertTrue(result['active_manifest_unchanged'])
        self.assertTrue(result['excluded_from_argocd'])
        self.assertIn('published_image_digest',result['release_gates'])
        self.assertEqual(result['proposed_schema'],'public')

    def test_materialization_requires_registry_digest_not_local_image_or_tag(self):
        module=self.load()
        for image in (None,'','latest','sha256:'+'a'*64,
                      'ghcr.io/benkim0414/hindsight-specialist-memory:latest',
                      module.IMAGE_PLACEHOLDER):
            with self.subTest(image=image),self.assertRaises(ValueError):module.materialize(image)
        # Synthetic UNIT-only digest. No artifact availability is asserted.
        image='ghcr.io/benkim0414/hindsight-specialist-memory@sha256:'+'a'*64
        patch=module.materialize(image)
        self.assertEqual(patch['spec']['template']['spec']['containers'][0]['image'],image)
        self.assertEqual(module.check()['status'],'DRAFT_BLOCKED')

    def test_patch_cannot_change_providers_volumes_strategy_or_manual_sync(self):
        module=self.load();original=module.read_patch()
        variants=[]
        p=copy.deepcopy(original);p['spec']['replicas']=2;variants.append(p)
        p=copy.deepcopy(original);p['spec']['template']['spec']['volumes']=[];variants.append(p)
        p=copy.deepcopy(original);p['spec']['template']['spec']['containers'][0]['env'].append(
            {'name':'HINDSIGHT_API_LLM_PROVIDER','value':'none'});variants.append(p)
        p=copy.deepcopy(original);p['spec']['template']['spec']['containers'][0]['env'][0]['value']='wrong';variants.append(p)
        for patch in variants:
            with self.assertRaises(ValueError):module.check_patch(patch)

    def test_secret_refs_are_required_and_legacy_key_is_reused_only_by_reference(self):
        module=self.load();patch=module.read_patch()
        env={v['name']:v for v in patch['spec']['template']['spec']['containers'][0]['env']}
        old=env['HINDSIGHT_API_OPERATION_VALIDATOR_API_KEY']['valueFrom']['secretKeyRef']
        self.assertEqual(old,{'name':'hindsight-api-credentials','key':'HINDSIGHT_API_TENANT_API_KEY','optional':False})
        for prefix in ('HINDSIGHT_API_TENANT_','HINDSIGHT_API_OPERATION_VALIDATOR_'):
            for suffix in module.NEW_KEY_FIELDS:
                ref=env[prefix+suffix]['valueFrom']['secretKeyRef']
                self.assertEqual(ref['name'],'hindsight-specialist-memory-credentials')
                self.assertEqual(ref['key'],suffix)
                self.assertIs(ref['optional'],False)
        p=copy.deepcopy(patch)
        p['spec']['template']['spec']['containers'][0]['env'][-1]={'name':'BAD','value':'fixture-must-not-be-proposed'}
        with self.assertRaises(ValueError):module.check_patch(p)

if __name__=='__main__':unittest.main()
