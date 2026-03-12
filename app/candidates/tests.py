import pandas as pd
from django.test import TestCase
from unittest.mock import patch

from candidates.gal_association import associate_galaxy


class GladeAssociationTests(TestCase):
    @patch("candidates.gal_association.get_glade")
    def test_associate_galaxy_returns_redshift_only_for_spectroscopic_distance_flags(self, mock_get_glade):
        mock_get_glade.return_value = pd.DataFrame(
            [
                {
                    "GWGC": "GAL-PHOTO",
                    "HyperLEDA": None,
                    "2MASS": None,
                    "wiseX": None,
                    "SDSS-DR16Q": None,
                    "RA": 10.0,
                    "Dec": 20.0,
                    "d_L": 100.0,
                    "dist_flag": 1,
                    "z_helio": 0.123,
                },
                {
                    "GWGC": "GAL-SPEC",
                    "HyperLEDA": None,
                    "2MASS": None,
                    "wiseX": None,
                    "SDSS-DR16Q": None,
                    "RA": 30.0,
                    "Dec": 40.0,
                    "d_L": 200.0,
                    "dist_flag": 2,
                    "z_helio": 0.456,
                },
            ]
        )

        photo_name, photo_dist, photo_redshift = associate_galaxy(10.0, 20.0, radius=30.0)
        spec_name, spec_dist, spec_redshift = associate_galaxy(30.0, 40.0, radius=30.0)

        self.assertEqual((photo_name, photo_dist, photo_redshift), ("GAL-PHOTO (GWGC)", 100.0, None))
        self.assertEqual((spec_name, spec_dist, spec_redshift), ("GAL-SPEC (GWGC)", 200.0, 0.456))
