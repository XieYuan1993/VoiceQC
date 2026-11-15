import uuid

import pytest
from app.routers.config import SUPERVISOR_DEFAULT, _v_supervisor, supervisor_notification


@pytest.mark.parametrize(
    "changes",
    [
        {"email_enabled": True},
        {"sms_enabled": True},
        {"sms_enabled": "yes"},
        {"email_enabled": True, "email": "bad"},
        {"sms_enabled": True, "phone": "abc"},
    ],
)
def test_invalid_enabled_contacts(changes):
    with pytest.raises(ValueError):
        _v_supervisor(SUPERVISOR_DEFAULT | changes)


def test_independent_channels():
    _v_supervisor(dict(SUPERVISOR_DEFAULT))
    _v_supervisor(SUPERVISOR_DEFAULT | {"email_enabled": True, "email": "supervisor@example.test"})
    _v_supervisor(SUPERVISOR_DEFAULT | {"sms_enabled": True, "phone": "+852 6123 4567"})


@pytest.mark.anyio
async def test_contact_read_is_project_scoped_and_defaults_disabled():
    project = uuid.uuid4()

    class Session:
        async def get(self, model, key):
            assert key == (project, "notification.supervisor")
            return None

    assert (
        await supervisor_notification(project_id=project, user=None, session=Session())
        == SUPERVISOR_DEFAULT
    )
