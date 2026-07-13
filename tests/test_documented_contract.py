from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DocumentedContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pm_guide = (ROOT / "PM_GUIDE.html").read_text(encoding="utf-8")
        cls.common = (ROOT / "docs/check_modules/common.md").read_text(
            encoding="utf-8"
        )

    def test_pm_guide_states_top_level_check_contract(self):
        self.assertIn(
            "子任务顶层只输出 <code>{id, issues}</code>", self.pm_guide
        )

    def test_pm_guide_confirmation_issue_has_null_edit(self):
        self.assertIn(
            "<code>needs_confirmation: true</code> 和 <code>edit: null</code>",
            self.pm_guide,
        )

    def test_pm_guide_assigns_full_suggested_text_to_program(self):
        self.assertIn("完整建议译文只由程序生成", self.pm_guide)

    def test_common_marks_proper_names_optional(self):
        self.assertIn("`proper_names` 是可选模块", self.common)

    def test_common_preserves_empty_issue_entry_for_every_id(self):
        self.assertIn(
            '每个 id 无问题时也输出 `{"id": 0, "issues": []}`', self.common
        )


if __name__ == "__main__":
    unittest.main()
