import random
import string

def generate_password(length=12, use_uppercase=True, use_lowercase=True, use_digits=True, use_symbols=True):
    """
    Generates a random password based on specified criteria.

    Args:
        length: The desired length of the password.
        use_uppercase: Whether to include uppercase letters.
        use_lowercase: Whether to include lowercase letters.
        use_digits: Whether to include digits.
        use_symbols: Whether to include symbols.

    Returns:
        A randomly generated password as a string.
    """

    characters = ""
    if use_uppercase:
        characters += string.ascii_uppercase
    if use_lowercase:
        characters += string.ascii_lowercase
    if use_digits:
        characters += string.digits
    if use_symbols:
        characters += string.punctuation

    if not characters:
        raise ValueError("At least one character type must be selected.")

    password = ''.join(random.choice(characters) for _ in range(length))
    return password

# Example usage:
if __name__ == "__main__":
    try:
        password = generate_password(length=16, use_uppercase=True, use_lowercase=True, use_digits=True, use_symbols=True)
        print(f"Generated password: {password}")
    except ValueError as e:
        print(f"Error: {e}")
