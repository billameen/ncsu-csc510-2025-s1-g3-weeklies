from models import OrderStatus

def test_order_status_constants():
    """Ensure constants haven't drifted."""
    assert OrderStatus.ORDERED == 'Ordered'
    assert OrderStatus.PREPARING == 'Preparing'
    assert OrderStatus.DELIVERING == 'Delivering'
    assert OrderStatus.DELIVERED == 'Delivered'

def test_is_valid_status_true():
    """Test valid statuses return True."""
    assert OrderStatus.is_valid_status('Ordered') is True
    assert OrderStatus.is_valid_status('Delivered') is True

def test_is_valid_status_false():
    """Test invalid statuses return False."""
    assert OrderStatus.is_valid_status('Cooking') is False
    assert OrderStatus.is_valid_status('') is False
    assert OrderStatus.is_valid_status(None) is False

def test_valid_transitions_ordered():
    """Test allowed transitions from Ordered."""
    # Ordered -> Preparing (OK)
    assert OrderStatus.is_valid_transition(OrderStatus.ORDERED, OrderStatus.PREPARING) is True
    # Ordered -> Delivered (OK - skip steps)
    assert OrderStatus.is_valid_transition(OrderStatus.ORDERED, OrderStatus.DELIVERED) is True

def test_valid_transitions_preparing():
    """Test allowed transitions from Preparing."""
    # Preparing -> Delivering (OK)
    assert OrderStatus.is_valid_transition(OrderStatus.PREPARING, OrderStatus.DELIVERING) is True

def test_invalid_transitions_backward():
    """Test backward transitions are blocked."""
    # Delivered -> Ordered (No)
    assert OrderStatus.is_valid_transition(OrderStatus.DELIVERED, OrderStatus.ORDERED) is False
    # Delivering -> Preparing (No)
    assert OrderStatus.is_valid_transition(OrderStatus.DELIVERING, OrderStatus.PREPARING) is False

def test_invalid_transition_unknown_status():
    """Test transitions involving unknown statuses."""
    assert OrderStatus.is_valid_transition('AlienStatus', OrderStatus.ORDERED) is False
    assert OrderStatus.is_valid_transition(OrderStatus.ORDERED, 'AlienStatus') is False