"""Local XL naming must not change unrelated/custom quant names."""
from pathlib import Path
import unittest

import maya


class LocalXL(unittest.TestCase):
    def test_split_and_single_xl_share_the_installed_name(self):
        for name in ("GLM-5.3-Flash-UD-Q4_K_XL-00001-of-00006.gguf",
                     "GLM-5.3-Flash-UD-Q4_K_XL.gguf",
                     "glm-5.3-flash-ud-q4_k_xl-00001-of-00006.gguf"):
            with self.subTest(name=name):
                self.assertEqual(maya.quant_of(Path("models") / name), "Maya-XL")

    def test_other_local_quants_keep_their_names(self):
        self.assertEqual(maya.quant_of(Path("models/GLM-5.3-Flash-UD-Q4_K_M-00001-of-00006.gguf")), "UD-Q4_K_M")
        self.assertEqual(maya.quant_of(Path("custom/model.gguf")), "custom")

    def test_existing_maya_model_names_are_unchanged(self):
        for quant in ("Maya-M", "Maya-L"):
            mm = maya.MODELS[quant]
            self.assertEqual(maya.quant_of(Path("models") / maya.shard_names(mm)[0]), quant)


if __name__ == "__main__":
    unittest.main()
