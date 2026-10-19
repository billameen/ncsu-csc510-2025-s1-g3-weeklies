# Database Migrations

This folder contains database migration scripts for the Weeklies application.

## Available Migrations

### 1. `add_ticket_table.py`
Adds the support ticket system to the database.

**What it does:**
- Creates the `Ticket` table with all required columns
- Adds foreign key constraints for `usr_id` and `ord_id`
- Creates database indexes for performance
- Sets up automatic timestamp triggers

**Run:**
```bash
cd app
python migrations/add_ticket_table.py
```

### 2. `add_admin_column.py`
Adds admin functionality to the User table.

**What it does:**
- Adds `is_admin` column to the `User` table (INTEGER, default 0)
- Promotes the first existing user to admin, OR
- Creates a new admin user if no users exist

**Run:**
```bash
cd app
python migrations/add_admin_column.py
```

**Default Admin Credentials (if new user created):**
- Email: `admin@weeklies.com`
- Password: `admin123`
- ⚠️ **Change the password after first login!**

### 3. `add_plan_targets.py`
Adds the weekly planner's targets to the User table.

**What it does:**
- Adds `daily_calorie_target` (INTEGER, calories per day) to `User`
- Adds `weekly_budget_cents` (INTEGER, most a planned week may cost with tax and fees) to `User`
- Leaves both NULL for existing users ("not set yet"); users set them on Edit Profile

**Run:**
```bash
cd app
python migrations/add_plan_targets.py
```

`db/seed.sql` and the test schema in `tests/conftest.py` already include these columns.

## Running Migrations

Migrations are idempotent - they can be run multiple times safely. If a migration has already been applied, it will skip the changes.

```bash
# From the app directory
python migrations/add_ticket_table.py
python migrations/add_admin_column.py
python migrations/add_plan_targets.py
```

## Migration Order

If running all migrations from scratch:
1. `add_ticket_table.py` - Can run independently
2. `add_admin_column.py` - Can run independently

All migrations can be run in any order as they modify different tables/columns.

## Verifying Migrations

After running migrations, you can verify the changes:

```bash
# Check User table structure
sqlite3 CSC510_DB.db "PRAGMA table_info(User);"

# Check for admin users
sqlite3 CSC510_DB.db "SELECT usr_id, first_name, last_name, email, is_admin FROM User WHERE is_admin = 1;"

# Check Ticket table structure
sqlite3 CSC510_DB.db "PRAGMA table_info(Ticket);"

# Check Ticket table indexes
sqlite3 CSC510_DB.db "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='Ticket';"
```

## Creating New Migrations

When creating a new migration:

1. Create a new Python file in this directory
2. Follow the pattern of existing migrations:
   - Include a docstring explaining what the migration does
   - Implement idempotency checks (skip if already applied)
   - Use transactions (commit on success, rollback on error)
   - Include verification steps
   - Provide clear console output
3. Update this README with the new migration details
4. Test the migration on a copy of the database first

## Troubleshooting

**Migration fails with "database is locked":**
- Make sure the Flask app is not running
- Close any SQLite browser connections to the database

**Migration fails with "table already exists":**
- The migration has already been run
- Check the console output - it should skip gracefully

**Need to rollback a migration:**
- Migrations don't include automatic rollback
- Restore from a database backup if needed
- Or manually reverse the changes using SQL
