# None are working currently, need to fix playwright timeout issues.
# import pytest
# import re
# from playwright.sync_api import expect

# # --- Helper Function for Authentication ---

# def login_user(page, base_url, email="john@smith.com", password="password123"):
#     """
#     Performs a successful login using the seeded user credentials (from conftest.py).
    
#     This function must be called before navigating to any authenticated route 
#     like /profile, /orders, etc.
#     """
#     # 1. Navigate to the login page
#     page.goto(f"{base_url}/login")
    
#     # 2. Fill in the form fields
#     page.fill('input[name="email"]', email)
#     page.fill('input[name="password"]', password)
    
#     # 3. Submit the form and wait for navigation to complete (to '/')
#     page.click('button[type="submit"]')
    
#     # 4. Assert successful login by checking the final URL
#     expect(page).to_have_url(f"{base_url}/")

# # --- Error Modal Test (Updated) ---

# @pytest.mark.parametrize('error_code, expected_message', [
#     ('invalid_amount', 'The amount specified is invalid. Please enter a valid currency amount.'),
#     ('zero_amount', 'The amount must be greater than zero.'),
#     ('insufficient_funds', 'Insufficient funds in your wallet to complete this transfer.'),
#     ('recipient_not_found', 'The recipient email was not found in our system.'),
#     ('self_gift', 'Cannot gift funds to yourself. Please specify a different recipient.'),
#     # Add other error codes if necessary
# ])
# def test_error_modal_shows_correct_message_on_load(page, base_url, error_code, expected_message):
#     """
#     FIXED: Ensures the user is logged in before navigating to /profile?wallet_error=...
#     and uses the robust to_have_class assertion.
#     """
#     # 1. PREREQUISITE: Log in the user to maintain an authenticated session
#     login_user(page, base_url)

#     # 2. Navigate to the profile page with the error parameter
#     url_with_error = f"{base_url}/profile?wallet_error={error_code}"
#     # Use reload instead of goto to avoid hitting the Flask redirect logic if session is already active
#     page.goto(url_with_error) 

#     # 3. FIX: Assert the modal is visible by checking for the 'show' class.
#     # We use to_have_class with a regex to auto-wait for the class to be added by the JS.
#     error_modal = page.locator('#errorModal')
#     expect(error_modal).to_have_class(re.compile(r'.*show')) 
    
#     # 4. Assert the correct message is displayed
#     error_message = page.locator('#errorModalMessage').text_content()
#     assert error_message.strip() == expected_message, \
#         f"Modal message incorrect for code '{error_code}'. Got: '{error_message.strip()}'"

#     # 5. Assert URL is cleaned up after dismissal (e.g., by clicking OK)
#     page.locator('#okErrorBtn').click()
#     expect(error_modal).not_to_have_class(re.compile(r'.*show'))
#     assert 'wallet_error' not in page.url, "The 'wallet_error' URL parameter must be removed after modal dismissal."