import find_scp
import move_scp
import store_scp
import echo_scp


class CustomAE:
    def __init__(self, ae_title, host, port):
        # AE initialization code
        pass

    def start(self):
        # AE startup code
        pass

    def stop(self):
        # AE shutdown code
        pass

    def find(self, query_parameters):
        find_scp.handle_find(query_parameters)

    def move(self, move_parameters):
        move_scp.handle_move(move_parameters)

    def store(self, dataset):
        store_scp.handle_store(dataset)

    def echo(self):
        echo_scp.handle_echo()


if __name__ == "__main__":
    # Entry point for running the AE
    custom_ae = CustomAE("MY_AE_TITLE", "localhost", 11112)
    custom_ae.start()
