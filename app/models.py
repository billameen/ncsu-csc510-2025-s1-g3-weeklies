"""
Data models for the meal planning and food ordering application.

This module contains model classes that define data structures and validation
logic for the application's core entities.
"""


class OrderStatus:
    """
    Represents valid order statuses and transitions.
    
    This class defines the allowed order statuses and the valid transitions
    between them, enforcing a logical workflow progression for orders.
    
    Status Flow:
        Ordered -> Preparing -> Delivering -> Delivered
        Ordered -> Delivered (direct completion)
        Preparing -> Delivered (skip delivery)
    
    Attributes:
        ORDERED (str): Initial order status when order is placed
        PREPARING (str): Status when restaurant is preparing the order
        DELIVERING (str): Status when order is out for delivery
        DELIVERED (str): Final status when order is completed
        VALID_STATUSES (list): List of all valid status values
        TRANSITIONS (dict): Mapping of current status to allowed next statuses
    """
    
    # Status constants
    ORDERED = 'Ordered'
    PREPARING = 'Preparing'
    DELIVERING = 'Delivering'
    DELIVERED = 'Delivered'
    
    # List of all valid statuses
    VALID_STATUSES = [ORDERED, PREPARING, DELIVERING, DELIVERED]
    
    # Status transition rules
    # Maps current status -> list of allowed next statuses
    TRANSITIONS = {
        ORDERED: [PREPARING, DELIVERED],
        PREPARING: [DELIVERING, DELIVERED],
        DELIVERING: [DELIVERED],
        DELIVERED: []
    }
    
    @classmethod
    def is_valid_status(cls, status):
        """
        Check if a status value is valid.
        
        Args:
            status (str): The status value to validate
            
        Returns:
            bool: True if the status is in the allowed set, False otherwise
            
        Example:
            >>> OrderStatus.is_valid_status('Ordered')
            True
            >>> OrderStatus.is_valid_status('Invalid')
            False
        """
        return status in cls.VALID_STATUSES
    
    @classmethod
    def is_valid_transition(cls, current_status, new_status):
        """
        Check if a status transition is allowed.
        
        Validates that transitioning from current_status to new_status
        follows the defined workflow rules.
        
        Args:
            current_status (str): The current order status
            new_status (str): The proposed new status
            
        Returns:
            bool: True if the transition is allowed, False otherwise
            
        Example:
            >>> OrderStatus.is_valid_transition('Ordered', 'Preparing')
            True
            >>> OrderStatus.is_valid_transition('Delivered', 'Preparing')
            False
            >>> OrderStatus.is_valid_transition('Ordered', 'Delivering')
            False
        """
        if current_status not in cls.TRANSITIONS:
            return False
        return new_status in cls.TRANSITIONS[current_status]
