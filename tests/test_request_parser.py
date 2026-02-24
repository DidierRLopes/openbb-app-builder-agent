"""Unit tests for request parser (M2 Phase Gate).

Tests:
- Latest human message extraction edge cases
- Widget list extraction with empty/missing fields
- Tool-result extraction from fixture payloads
- Non-human final messages (should not execute)
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openbb_app_builder_agent.request_parser import (
    RequestContext,
    ToolResult,
    WidgetInfo,
    extract_conversation_id,
    parse_request,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def make_mock_request(messages=None, widgets=None):
    """Create a mock QueryRequest object."""
    mock = MagicMock()
    mock.messages = messages or []
    mock.widgets = widgets
    return mock


def make_mock_message(role: str, content: str = "", **kwargs):
    """Create a mock message object."""
    mock = MagicMock()
    mock.role = role
    mock.content = content
    # Set defaults for optional attributes to avoid MagicMock auto-creation
    mock.data = kwargs.pop("data", None)
    mock.function = kwargs.pop("function", None)
    mock.input_arguments = kwargs.pop("input_arguments", None)
    mock.extra_state = kwargs.pop("extra_state", None)
    for key, value in kwargs.items():
        setattr(mock, key, value)
    return mock


class TestLatestHumanMessageExtraction:
    """Tests for extracting the latest human message."""

    def test_single_human_message(self):
        """Single human message should be extracted."""
        request = make_mock_request(
            messages=[make_mock_message("human", "Hello world")]
        )
        context = parse_request(request)

        assert context.user_message == "Hello world"
        assert context.should_execute is True

    def test_multiple_human_messages(self):
        """Latest human message should be used."""
        request = make_mock_request(
            messages=[
                make_mock_message("human", "First message"),
                make_mock_message("ai", "Response"),
                make_mock_message("human", "Second message"),
            ]
        )
        context = parse_request(request)

        assert context.user_message == "Second message"
        assert context.should_execute is True

    def test_empty_messages(self):
        """Empty messages should return empty user message."""
        request = make_mock_request(messages=[])
        context = parse_request(request)

        assert context.user_message == ""
        assert context.should_execute is False

    def test_no_messages_attribute(self):
        """Missing messages should be handled."""
        request = make_mock_request(messages=None)
        context = parse_request(request)

        assert context.user_message == ""

    def test_ai_final_message_should_not_execute(self):
        """AI final message should set should_execute=False."""
        request = make_mock_request(
            messages=[
                make_mock_message("human", "Question"),
                make_mock_message("ai", "Answer"),
            ]
        )
        context = parse_request(request)

        assert context.user_message == "Question"
        assert context.should_execute is False

    def test_tool_final_message_should_not_execute(self):
        """Tool final message should set should_execute=False."""
        request = make_mock_request(
            messages=[
                make_mock_message("human", "Get data"),
                make_mock_message("ai", "Calling tool..."),
                make_mock_message("tool", function="get_data"),
            ]
        )
        context = parse_request(request)

        assert context.should_execute is False


class TestWidgetExtraction:
    """Tests for widget metadata extraction."""

    def test_no_widgets(self):
        """No widgets should return empty lists."""
        request = make_mock_request(
            messages=[make_mock_message("human", "Hello")],
            widgets=None,
        )
        context = parse_request(request)

        assert context.primary_widgets == []
        assert context.secondary_widgets == []
        assert context.has_widget_context() is False

    def test_primary_widgets_dict(self):
        """Primary widgets from dict should be extracted."""
        widgets = {
            "primary": [
                {
                    "uuid": "123",
                    "widget_id": "test_widget",
                    "name": "Test Widget",
                    "description": "A test widget",
                }
            ]
        }
        request = make_mock_request(
            messages=[make_mock_message("human", "Hello")],
            widgets=widgets,
        )
        context = parse_request(request)

        assert len(context.primary_widgets) == 1
        assert context.primary_widgets[0].uuid == "123"
        assert context.primary_widgets[0].widget_id == "test_widget"
        assert context.primary_widgets[0].name == "Test Widget"
        assert context.has_widget_context() is True

    def test_widget_missing_fields(self):
        """Widgets with missing fields should use defaults."""
        widgets = {
            "primary": [{"uuid": "123"}]  # Minimal widget
        }
        request = make_mock_request(
            messages=[make_mock_message("human", "Hello")],
            widgets=widgets,
        )
        context = parse_request(request)

        assert len(context.primary_widgets) == 1
        widget = context.primary_widgets[0]
        assert widget.uuid == "123"
        assert widget.widget_id == ""
        assert widget.name == ""
        assert widget.params == []

    def test_widget_with_params(self):
        """Widget params should be preserved."""
        widgets = {
            "primary": [
                {
                    "uuid": "123",
                    "widget_id": "stock_price",
                    "name": "Stock Price",
                    "params": [
                        {
                            "name": "ticker",
                            "type": "string",
                            "current_value": "AAPL",
                        }
                    ],
                }
            ]
        }
        request = make_mock_request(
            messages=[make_mock_message("human", "Hello")],
            widgets=widgets,
        )
        context = parse_request(request)

        assert len(context.primary_widgets[0].params) == 1
        assert context.primary_widgets[0].params[0]["current_value"] == "AAPL"


class TestToolResultExtraction:
    """Tests for tool result extraction."""

    def test_no_tool_messages(self):
        """No tool messages should return empty list."""
        request = make_mock_request(
            messages=[
                make_mock_message("human", "Hello"),
                make_mock_message("ai", "Hi there"),
            ]
        )
        context = parse_request(request)

        assert context.tool_results == []
        assert context.has_tool_results() is False

    def test_single_tool_result(self):
        """Single tool result should be extracted."""
        tool_msg = make_mock_message(
            "tool",
            function="get_widget_data",
            input_arguments={"widget_uuid": "123"},
            data=[{"value": 100}],
            extra_state={},
        )
        request = make_mock_request(
            messages=[
                make_mock_message("human", "Get data"),
                make_mock_message("ai", "Calling..."),
                tool_msg,
            ]
        )
        context = parse_request(request)

        assert len(context.tool_results) == 1
        assert context.tool_results[0].function == "get_widget_data"
        assert context.tool_results[0].data == [{"value": 100}]
        assert context.has_tool_results() is True

    def test_tool_result_string_data(self):
        """Tool result with string data should be parsed."""
        tool_msg = make_mock_message(
            "tool",
            function="get_data",
            input_arguments={},
            data='{"result": "success"}',
            extra_state={},
        )
        request = make_mock_request(messages=[tool_msg])
        context = parse_request(request)

        assert len(context.tool_results) == 1
        assert context.tool_results[0].data == {"result": "success"}
        assert context.tool_results[0].data_raw == '{"result": "success"}'


class TestConversationIdExtraction:
    """Tests for conversation ID extraction."""

    def test_extract_from_first_message(self):
        """Conversation ID should be derived from first message."""
        request = make_mock_request(
            messages=[make_mock_message("human", "Hello")]
        )
        conv_id = extract_conversation_id(request)

        assert conv_id is not None
        assert len(conv_id) == 16

    def test_same_message_same_id(self):
        """Same first message should produce same ID."""
        request1 = make_mock_request(
            messages=[make_mock_message("human", "Hello")]
        )
        request2 = make_mock_request(
            messages=[make_mock_message("human", "Hello")]
        )

        id1 = extract_conversation_id(request1)
        id2 = extract_conversation_id(request2)

        assert id1 == id2

    def test_different_message_different_id(self):
        """Different first messages should produce different IDs."""
        request1 = make_mock_request(
            messages=[make_mock_message("human", "Hello")]
        )
        request2 = make_mock_request(
            messages=[make_mock_message("human", "Goodbye")]
        )

        id1 = extract_conversation_id(request1)
        id2 = extract_conversation_id(request2)

        assert id1 != id2

    def test_empty_messages_returns_none(self):
        """Empty messages should return None."""
        request = make_mock_request(messages=[])
        conv_id = extract_conversation_id(request)

        assert conv_id is None


class TestRequestContextSerialization:
    """Tests for RequestContext serialization."""

    def test_to_dict(self):
        """RequestContext should serialize to dict."""
        context = RequestContext(
            user_message="Test message",
            history=[{"role": "human", "content": "Test"}],
            primary_widgets=[
                WidgetInfo(uuid="123", widget_id="test", name="Test")
            ],
            tool_results=[
                ToolResult(function="test_func", data={"key": "value"})
            ],
        )

        data = context.to_dict()

        assert data["user_message"] == "Test message"
        assert len(data["primary_widgets"]) == 1
        assert len(data["tool_results"]) == 1
        assert data["should_execute"] is True

    def test_serialization_json_safe(self):
        """Serialized context should be JSON-safe."""
        context = RequestContext(
            user_message="Test",
            primary_widgets=[WidgetInfo(uuid="123", widget_id="test", name="Test")],
        )

        # Should not raise
        json_str = json.dumps(context.to_dict())
        assert json_str is not None


class TestFixturePayloadParsing:
    """Tests using actual fixture payloads."""

    def test_single_message_fixture(self):
        """Parse single_message.json fixture."""
        fixture_path = FIXTURES_DIR / "single_message.json"
        if not fixture_path.exists():
            pytest.skip("Fixture not found")

        with open(fixture_path) as f:
            payload = json.load(f)

        # Create mock from fixture
        messages = [
            make_mock_message(m["role"], m.get("content", ""))
            for m in payload.get("messages", [])
        ]
        request = make_mock_request(messages=messages)
        context = parse_request(request)

        assert context.user_message != ""
        assert context.should_execute is True

    def test_widget_fixture(self):
        """Parse message_with_primary_widget.json fixture."""
        fixture_path = FIXTURES_DIR / "message_with_primary_widget.json"
        if not fixture_path.exists():
            pytest.skip("Fixture not found")

        with open(fixture_path) as f:
            payload = json.load(f)

        messages = [
            make_mock_message(m["role"], m.get("content", ""))
            for m in payload.get("messages", [])
        ]
        request = make_mock_request(
            messages=messages,
            widgets=payload.get("widgets"),
        )
        context = parse_request(request)

        assert context.has_widget_context() is True
        assert len(context.primary_widgets) > 0
