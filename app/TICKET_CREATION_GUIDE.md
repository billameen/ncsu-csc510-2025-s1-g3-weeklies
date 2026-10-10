# Support Ticket Creation Guide

## Overview

Support tickets allow customers to report issues with their orders. The ticket system is integrated into the user profile page and connects customers with administrators who can respond and resolve issues.

## How Customers Create Tickets

### Step 1: Navigate to Profile
1. Log in to your account
2. Click **"Profile"** in the navigation menu
3. Scroll to the **"Order History"** section

### Step 2: Find the Order
Locate the order you want to report an issue about in your order history table.

### Step 3: Click "Report Issue"
Each order has a **"Report Issue"** button in the rightmost column. Click it to open the report modal.

### Step 4: Fill Out the Form
A modal dialog will appear with:
- **Order Number** (automatically filled)
- **Message Field** (describe your issue)
- **Character Counter** (minimum 10 characters required)

### Step 5: Submit
1. Type your issue description (at least 10 characters)
2. The submit button becomes enabled when you reach 10 characters
3. Click **"Submit Report"** to create the ticket

### Step 6: Confirmation
- You'll be redirected back to your profile
- A success message will appear
- Your new ticket will be visible in the "My Support Tickets" section below

## Ticket Validation Rules

The system enforces these rules:

1. **Authentication Required**: Must be logged in
2. **Order Ownership**: Can only report issues for your own orders
3. **Message Length**: Minimum 10 characters required
4. **Order Exists**: Order ID must be valid and exist in database

## Ticket Information Displayed

Once created, tickets show:
- **Ticket ID** (e.g., #45)
- **Status** (Open, In Progress, Resolved, Closed)
- **Related Order** (Order #123)
- **Your Message** (the issue description)
- **Admin Response** (when admin replies)
- **Created Date** (when ticket was submitted)

## Backend Process

When you submit a ticket:

1. **POST Request** sent to `/support/submit`
2. **Validation** checks:
   - User is authenticated
   - Order exists and belongs to user
   - Message is at least 10 characters
3. **Database Insert**:
   ```sql
   INSERT INTO Ticket (usr_id, ord_id, message, status)
   VALUES (?, ?, ?, 'Open')
   ```
4. **Initial Status**: Set to "Open"
5. **Timestamps**: `created_at` and `updated_at` automatically set
6. **Redirect**: Back to profile with success message

## Ticket Lifecycle

```
Open → In Progress → Resolved → Closed
```

1. **Open**: Initial state when customer creates ticket
2. **In Progress**: Admin is working on the issue
3. **Resolved**: Issue has been addressed
4. **Closed**: Ticket is finalized

## Admin Response

Admins can:
- View all tickets in the admin dashboard (`/admin`)
- Add responses to tickets
- Update ticket status
- When admin adds a response to an "Open" ticket, status automatically changes to "In Progress"

## Multiple Tickets

- You can create multiple tickets for the same order
- Each ticket gets a unique ticket ID
- All tickets are tracked independently

## Error Handling

If submission fails, you'll see error messages for:
- **Invalid Order**: Order ID doesn't exist
- **Message Too Short**: Less than 10 characters
- **Unauthorized**: Trying to report issue for someone else's order
- **Not Logged In**: Must authenticate first

## Technical Details

### Database Schema
```sql
CREATE TABLE Ticket (
    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
    usr_id INTEGER NOT NULL,
    ord_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    response TEXT,
    status TEXT NOT NULL DEFAULT 'Open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usr_id) REFERENCES User(usr_id),
    FOREIGN KEY (ord_id) REFERENCES "Order"(ord_id)
);
```

### API Endpoint
- **URL**: `/support/submit`
- **Method**: POST
- **Content-Type**: application/x-www-form-urlencoded
- **Parameters**:
  - `ord_id` (int): Order ID
  - `message` (string): Issue description (min 10 chars)

### Response
- **Success**: Redirect to `/profile?ticket_success=1&ticket_id={id}`
- **Error**: Redirect to `/profile?ticket_error={error_type}`

## UI Features

### Real-time Character Counter
- Shows current character count
- Changes color based on length:
  - Gray: 0 characters
  - Yellow: 1-9 characters
  - Green: 10+ characters (valid)

### Submit Button State
- **Disabled**: When message < 10 characters
- **Enabled**: When message ≥ 10 characters

### Modal Keyboard Support
- **Escape Key**: Closes the modal
- **Auto-focus**: Message field gets focus when modal opens

## Example Workflow

1. Customer orders pizza from "Pizza Palace"
2. Pizza arrives cold
3. Customer goes to Profile → Order History
4. Clicks "Report Issue" on that order
5. Types: "Pizza arrived cold and was 30 minutes late"
6. Clicks "Submit Report"
7. Ticket #45 is created with status "Open"
8. Admin sees ticket in dashboard
9. Admin responds: "We apologize for the inconvenience. We've issued a refund."
10. Ticket status changes to "In Progress"
11. Customer sees response in their profile
12. Admin marks ticket as "Resolved"

## Testing

To test ticket creation:
1. Log in as a regular user (not admin)
2. Go to Profile
3. Find any order in your history
4. Click "Report Issue"
5. Enter a message (at least 10 characters)
6. Submit
7. Verify ticket appears in "My Support Tickets" section
8. Log in as admin to see the ticket in admin dashboard
