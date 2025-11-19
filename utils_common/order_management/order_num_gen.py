"""
Order number generation and encoding utilities
  . Generates unique order numbers from recipient phone numbers
  . Encodes 4-digit numbers into 4-character strings using hashing
  . Uses date-based salting for uniqueness
  . Provides decoding functionality for order number validation
  Functions/Classes:
    . create_order_number
    . decode_order_number
"""

# %%
import hashlib
from datetime import datetime


SALT = "mySalt"
ALPHABET = "abcdefghijklmnopqrstuvwxyz"

def create_order_number(recipient: str) -> str:
    number = recipient[-4:]
    """Encodes a 4-digit number string into a 4-character string."""
    if not len(number) == 4 or not number.isdigit():
        raise ValueError("Number must be a 4-digit string")
    
    date_string = datetime.now().strftime("%Y%m%d")
    salted_number = f"{number}{SALT}{date_string}"
    hashed_number = hashlib.sha256(salted_number.encode()).hexdigest()
    
    encoded_chars = ""
    for i in range(4):
        index = int(hashed_number[i*2:i*2+2], 16) % len(ALPHABET)
        encoded_chars += ALPHABET[index]
    return encoded_chars

def decode_order_number(encoded_string: str) -> str:
    """Decodes a 4-character string back into a 4-digit number string."""
    if len(encoded_string) != 4:
        raise ValueError("Encoded string must be 4 characters long")
    
    for number in range(0, 10000): # Modified range to include numbers with leading zeros
        number_str = str(number).zfill(4) # Added zfill to make sure number is 4 digits
        if create_order_number(number_str) == encoded_string:
            return number_str
    raise ValueError("Invalid encoded string")

if __name__ == '__main__':
    number = "919182730754"
    encoded = create_order_number(number)
    print(f"Original Number: {number}")
    print(f"Encoded String: {encoded.upper()}")

    decoded = decode_order_number(encoded)
    print(f"Decoded Number: {decoded}")

    # get sequNumber for the date_ts, insert_ts = datetime.now().isoformat()
    # create order
        # get seq num
        # insert order