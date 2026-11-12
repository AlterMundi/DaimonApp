"""Served-byte fingerprints, not catalogue IDs; no provider or actor writes."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.client_build import fingerprint, stamp, MARKER, workshop_assets
from dashboard import shared_asset_release as r
from dashboard_shared_asset_release import Releases


class Build(Releases):
    def test_selected_bytes_and_not_publication_metadata_define_label(self):
        public=self.root/'public';public.mkdir();self.vendor.rename(public/'avatar-workshop');self.vendor=public/'avatar-workshop'
        state=self.root/'state';self.releases=state/'shared-app-assets/avatar-workshop'
        a=r.prepare(self.releases,self.transfer(),self.vendor);r.activate(self.releases,a['release'],None,self.vendor)
        release,assets=workshop_assets(public,state);one=fingerprint(b'shell',assets)
        self.assertEqual(release,a['release'])
        self.assertIn(('avatar-workshop/experiments/school-avatar-quest/index.html',b'old editor'),assets)
        self.metadata['author']='Updated publication attribution';self.write_metadata()
        b=r.prepare(self.releases,self.transfer(),self.vendor);r.activate(self.releases,b['release'],r.current(self.releases),self.vendor)
        self.assertEqual(fingerprint(b'shell',workshop_assets(public,state)[1]),one)
        (self.vendor/'experiments/school-avatar-quest/index.html').write_bytes(b'new editor');self.write_metadata()
        c=r.prepare(self.releases,self.transfer(),self.vendor);r.activate(self.releases,c['release'],r.current(self.releases),self.vendor)
        self.assertNotEqual(fingerprint(b'shell',workshop_assets(public,state)[1]),one)
        self.assertEqual(r.asset(self.releases,a['release'],'experiments/school-avatar-quest/index.html',self.vendor)[0],b'old editor')
        label=stamp(MARKER,one)
        self.assertIn('ui <code>',label);self.assertEqual(label.count('<span>'),12)
        self.assertNotIn(' hidden',label)


if __name__=='__main__':unittest.main()
