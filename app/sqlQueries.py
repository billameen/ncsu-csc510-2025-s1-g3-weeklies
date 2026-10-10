import sqlite3


def create_connection(db_file: str):
    """
    Create and return a connection to the specified SQLite database.
    Args:
        db_file (str): Path to the SQLite database file.
    Returns:
        sqlite3.Connection | None: Connection object if successful, None otherwise.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
    except sqlite3.Error as e:
        print(e)
    return conn


def close_connection(conn):
    """
    Close an existing SQLite database connection.
    Args:
        conn (sqlite3.Connection): Connection object to close.
    Returns:
        None
    """
    if conn:
        conn.close()


def execute_query(conn, query: str, params=()):
    """
    Execute a single SQL query with optional parameters.
    Args:
        conn (sqlite3.Connection): Active database connection.
        query (str): SQL query string to execute.
        params (tuple, optional): Parameters to safely substitute into the query.
    Returns:
        sqlite3.Cursor | None: Cursor object if successful, None if an error occurred.
    """
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        return cur
    except sqlite3.Error as e:
        print(e)
        return None


def fetch_all(conn, query: str, params=()):
    """
    Execute a query and return all fetched rows.
    Args:
        conn (sqlite3.Connection): Active database connection.
        query (str): SQL query string to execute.
        params (tuple, optional): Parameters to safely substitute into the query.
    Returns:
        list: A list of result rows (each as a tuple). Empty list if no results or on failure.
    """
    cur = execute_query(conn, query, params)
    if cur:
        return cur.fetchall()
    return []


def fetch_one(conn, query: str, params=()):
    """
    Execute a query and return the first result row.
    Args:
        conn (sqlite3.Connection): Active database connection.
        query (str): SQL query string to execute.
        params (tuple, optional): Parameters to safely substitute into the query.
    Returns:
        tuple | None: The first row as a tuple, or None if no result or on failure.
    """
    cur = execute_query(conn, query, params)
    if cur:
        return cur.fetchone()
    return None


# ============================================================================
# Ticket Management Functions
# ============================================================================

def create_ticket(conn, usr_id: int, ord_id: int, message: str):
    """
    Create a new support ticket in the database.
    
    Args:
        conn (sqlite3.Connection): Active database connection.
        usr_id (int): User ID who is submitting the ticket.
        ord_id (int): Order ID related to the ticket.
        message (str): The issue description (must be at least 10 characters).
    
    Returns:
        int | None: The ticket_id of the newly created ticket, or None if creation failed.
    
    Example:
        >>> conn = create_connection('CSC510_DB.db')
        >>> ticket_id = create_ticket(conn, usr_id=1, ord_id=123, message="Food was cold")
        >>> close_connection(conn)
    """
    query = """
        INSERT INTO Ticket (usr_id, ord_id, message, status)
        VALUES (?, ?, ?, 'Open')
    """
    cur = execute_query(conn, query, (usr_id, ord_id, message))
    if cur:
        return cur.lastrowid
    return None


def get_tickets_by_user(conn, usr_id: int):
    """
    Fetch all support tickets for a specific user.
    
    Retrieves tickets with associated order information, sorted by creation date
    (newest first).
    
    Args:
        conn (sqlite3.Connection): Active database connection.
        usr_id (int): User ID to fetch tickets for.
    
    Returns:
        list: List of ticket rows with order details. Each row contains:
              (ticket_id, usr_id, ord_id, message, response, status, 
               created_at, updated_at, order_details)
              Empty list if no tickets found or on failure.
    
    Example:
        >>> conn = create_connection('CSC510_DB.db')
        >>> tickets = get_tickets_by_user(conn, usr_id=1)
        >>> close_connection(conn)
    """
    query = """
        SELECT 
            t.ticket_id,
            t.usr_id,
            t.ord_id,
            t.message,
            t.response,
            t.status,
            t.created_at,
            t.updated_at,
            o.details
        FROM Ticket t
        LEFT JOIN "Order" o ON t.ord_id = o.ord_id
        WHERE t.usr_id = ?
        ORDER BY t.created_at DESC
    """
    return fetch_all(conn, query, (usr_id,))


def get_all_tickets(conn):
    """
    Fetch all support tickets for the admin dashboard.
    
    Retrieves all tickets with associated user and order information,
    sorted by status priority (Open first) and then by creation date.
    
    Args:
        conn (sqlite3.Connection): Active database connection.
    
    Returns:
        list: List of all ticket rows with user and order details. Each row contains:
              (ticket_id, usr_id, ord_id, message, response, status,
               created_at, updated_at, user_first_name, user_last_name, order_details)
              Empty list if no tickets found or on failure.
    
    Example:
        >>> conn = create_connection('CSC510_DB.db')
        >>> all_tickets = get_all_tickets(conn)
        >>> close_connection(conn)
    """
    query = """
        SELECT 
            t.ticket_id,
            t.usr_id,
            t.ord_id,
            t.message,
            t.response,
            t.status,
            t.created_at,
            t.updated_at,
            u.first_name as user_first_name,
            u.last_name as user_last_name,
            o.details as order_details
        FROM Ticket t
        LEFT JOIN User u ON t.usr_id = u.usr_id
        LEFT JOIN "Order" o ON t.ord_id = o.ord_id
        ORDER BY 
            CASE t.status
                WHEN 'Open' THEN 1
                WHEN 'In Progress' THEN 2
                WHEN 'Resolved' THEN 3
                WHEN 'Closed' THEN 4
                ELSE 5
            END,
            t.created_at DESC
    """
    return fetch_all(conn, query)


def update_ticket_status(conn, ticket_id: int, new_status: str):
    """
    Update the status of a support ticket.
    
    Valid statuses are: 'Open', 'In Progress', 'Resolved', 'Closed'.
    The updated_at timestamp is automatically updated by database trigger.
    
    Args:
        conn (sqlite3.Connection): Active database connection.
        ticket_id (int): ID of the ticket to update.
        new_status (str): New status value.
    
    Returns:
        bool: True if update was successful, False otherwise.
    
    Example:
        >>> conn = create_connection('CSC510_DB.db')
        >>> success = update_ticket_status(conn, ticket_id=45, new_status='In Progress')
        >>> close_connection(conn)
    """
    query = """
        UPDATE Ticket
        SET status = ?
        WHERE ticket_id = ?
    """
    cur = execute_query(conn, query, (new_status, ticket_id))
    return cur is not None


def update_ticket_response(conn, ticket_id: int, response: str, auto_update_status: bool = True):
    """
    Update the response field of a support ticket.
    
    Optionally automatically updates status to 'In Progress' if current status is 'Open'.
    The updated_at timestamp is automatically updated by database trigger.
    
    Args:
        conn (sqlite3.Connection): Active database connection.
        ticket_id (int): ID of the ticket to update.
        response (str): Administrator's response text.
        auto_update_status (bool): If True, automatically set status to 'In Progress' 
                                   when adding response to an 'Open' ticket. Default is True.
    
    Returns:
        bool: True if update was successful, False otherwise.
    
    Example:
        >>> conn = create_connection('CSC510_DB.db')
        >>> success = update_ticket_response(conn, ticket_id=45, 
        ...                                  response="We're looking into this...")
        >>> close_connection(conn)
    """
    if auto_update_status:
        # Check current status and update if it's 'Open'
        query = """
            UPDATE Ticket
            SET response = ?,
                status = CASE 
                    WHEN status = 'Open' THEN 'In Progress'
                    ELSE status
                END
            WHERE ticket_id = ?
        """
    else:
        query = """
            UPDATE Ticket
            SET response = ?
            WHERE ticket_id = ?
        """
    
    cur = execute_query(conn, query, (response, ticket_id))
    return cur is not None
