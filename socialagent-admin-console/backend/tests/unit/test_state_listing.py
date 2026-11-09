# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Schedule firing records must not appear as users in either state view."""

import json
from unittest.mock import call, patch

import pytest

REGISTRY = {"region": "us-east-1", "outputs": {"state_table_name": "bot-dev-state"}}
USER_ITEM = {
    "pk": "+15555550100",
    "sk": "_schedule#reminder",
    "data": '{"text": "Keep this user state"}',
    "ttl": 1800000000,
}
FIRING_ITEM = {
    "pk": "_schedule#firing-id-hash",
    "sk": "claim#2026-11-01T12:00:00Z",
    "data": "true",
    "ttl": 1800000000,
}
LAST_KEY = {"pk": FIRING_ITEM["pk"], "sk": FIRING_ITEM["sk"]}


@pytest.mark.unit
@pytest.mark.parametrize("handler_name", ["handle_get_state", "handle_list_all_state"])
@pytest.mark.parametrize(
    "pages,has_user,scanned_pages",
    [
        ([{"Items": [FIRING_ITEM, USER_ITEM]}], True, 1),
        (
            [
                {"Items": [FIRING_ITEM], "LastEvaluatedKey": LAST_KEY},
                {"Items": [USER_ITEM]},
            ],
            True,
            2,
        ),
        ([{"Items": [FIRING_ITEM]}], False, 1),
        (
            [
                {
                    "Items": [
                        dict(FIRING_ITEM, pk=f"_schedule#{i}") for i in range(2000)
                    ],
                    "LastEvaluatedKey": {
                        "pk": "_schedule#1999",
                        "sk": FIRING_ITEM["sk"],
                    },
                },
                {"Items": [USER_ITEM]},
            ],
            False,
            1,
        ),
    ],
    ids=[
        "mixed-page",
        "user-after-internal-only-page",
        "only-internal-records",
        "scan-cap",
    ],
)
def test_state_lists_exclude_schedule_partitions(
    handler_name, pages, has_user, scanned_pages
):
    # Import after conftest's aws_env fixture has supplied the backend config.
    from routes import state

    with (
        patch.object(state, "_get_registry", return_value=REGISTRY),
        patch.object(state, "_get_all_registries", return_value={"bot-dev": REGISTRY}),
        patch.object(state, "boto3") as b3,
    ):
        scan = b3.resource.return_value.Table.return_value.scan
        scan.side_effect = pages
        response = getattr(state, handler_name)({"id": "bot-dev"}, {})

    assert response["statusCode"] == 200
    expected = []
    if has_user:
        expected.append(
            {
                "phone": "+15555550100",
                "key": "_schedule#reminder",
                "value": {"text": "Keep this user state"},
                "ttl": 1800000000,
            }
        )
        if handler_name == "handle_list_all_state":
            expected[0]["stack"] = "bot-dev"
    assert json.loads(response["body"]) == expected
    expected_calls = [call()]
    if scanned_pages > 1:
        expected_calls.append(call(ExclusiveStartKey=LAST_KEY))
    assert scan.call_args_list == expected_calls
