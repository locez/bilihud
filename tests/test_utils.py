from bilihud.utils import validate_room_id

def test_validate_room_id():
    """Test room ID validation logic"""
    assert validate_room_id("123") is True
    assert validate_room_id("2145") is True
    
    # Invalid cases
    assert validate_room_id("0") is False
    assert validate_room_id("-1") is False
    assert validate_room_id("abc") is False
    assert validate_room_id("") is False
