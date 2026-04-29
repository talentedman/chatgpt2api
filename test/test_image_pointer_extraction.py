from __future__ import annotations

import unittest

from services.openai_backend_api import OpenAIBackendAPI
from services.protocol.conversation import extract_conversation_ids


class ImagePointerExtractionTests(unittest.TestCase):
    def test_extract_conversation_ids_supports_extended_file_id_format(self):
        payload = (
            '{"conversation_id":"conv_1","p1":"file-service://file_abc-123_def",'
            '"p2":"sediment://file_zzz-789_ghi","p3":"file_upload"}'
        )
        conversation_id, file_ids, sediment_ids = extract_conversation_ids(payload)
        self.assertEqual(conversation_id, "conv_1")
        self.assertIn("file_abc-123_def", file_ids)
        self.assertIn("file_zzz-789_ghi", sediment_ids)

    def test_extract_image_tool_records_collects_nested_asset_pointers(self):
        api = OpenAIBackendAPI(access_token="")
        data = {
            "mapping": {
                "node_1": {
                    "message": {
                        "author": {"role": "tool"},
                        "metadata": {"async_task_type": "image_gen"},
                        "create_time": 2,
                        "content": {
                            "content_type": "json",
                            "parts": [
                                {
                                    "asset_pointer": "file-service://file_main_123",
                                    "extra": {
                                        "nested": [
                                            "ignored",
                                            {"asset_pointer": "sediment://file_alt_456"},
                                        ]
                                    },
                                }
                            ],
                        },
                    }
                },
                "node_2": {
                    "message": {
                        "author": {"role": "assistant"},
                        "metadata": {"async_task_type": "image_gen"},
                        "create_time": 1,
                        "content": {"parts": [{"asset_pointer": "file-service://file_should_ignore"}]},
                    }
                },
            }
        }
        records = api._extract_image_tool_records(data)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["message_id"], "node_1")
        self.assertIn("file_main_123", records[0]["file_ids"])
        self.assertIn("file_alt_456", records[0]["sediment_ids"])

    def test_extract_latest_assistant_text_prefers_newest_non_empty(self):
        api = OpenAIBackendAPI(access_token="")
        data = {
            "mapping": {
                "a1": {
                    "message": {
                        "author": {"role": "assistant"},
                        "create_time": 10,
                        "content": {"content_type": "text", "parts": ["旧文案"]},
                    }
                },
                "a2": {
                    "message": {
                        "author": {"role": "assistant"},
                        "create_time": 20,
                        "content": {"content_type": "model_editable_context", "parts": []},
                    }
                },
                "a3": {
                    "message": {
                        "author": {"role": "assistant"},
                        "create_time": 30,
                        "content": {"content_type": "text", "parts": ["最新拒绝文案"]},
                    }
                },
            }
        }
        self.assertEqual(api._extract_latest_assistant_text(data), "最新拒绝文案")


if __name__ == "__main__":
    unittest.main()
