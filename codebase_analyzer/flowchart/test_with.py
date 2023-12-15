class MyConnection:
    def __enter__(self):
        # Setup code goes here. This can be used to establish a connection.
        print("Opening connection.")
        return self  # This is what is assigned to the variable after 'as'

    def __exit__(self, exc_type, exc_value, traceback):
        # Teardown code goes here. This is used to close the connection.
        print("Closing connection.")
        # Return False to propagate exceptions, True to suppress them
        return False


# Using the custom context manager
with MyConnection() as conn:
    print("Inside the block with the connection.")
    # Perform operations with the connection here
