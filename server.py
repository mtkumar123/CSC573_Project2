import socket
import random


def write_file(data):
    with open("result.txt", mode="ab") as f:
        f.write(data)


def carry_around_add(a, b):
    c = a + b
    return (c & 0xffff) + (c >> 16)


def verify_checksum(checksum, data):
    s = 0
    # Check if length of data is even or odd. For calculating checksum we need to do
    # ones complement of ones complement sum of 16 bit words. Therefore if the
    # data has an even number of bytes this will work out. However if the data has
    # an odd number of bytes we should add one byte of zeroes to do zero padding
    if len(data) % 2 != 0:
        data = data + b"0"
    for i in range(0, len(data), 2):
        w = data[i] + (data[i + 1] << 8)
        s = carry_around_add(s, w)
    # check_this_value contains the checksum computed off the data. We need to convert it to 16 bits and compare with
    # the checksum received from the packet
    check_this_value = ~s & 0xffff
    check_this_value = '{0:016b}'.format(check_this_value).encode()
    if checksum == check_this_value:
        return True
    else:
        return False


def create_segment(ack):
    zero_padding = '{0:016b}'.format(0).encode()
    ack_indicator = b"1010101010101010"
    segment = ack + zero_padding + ack_indicator
    return segment


def check_probability(p):
    r = random.random()
    if r <= p:
        print("R {} less than P {}".format(r, p))
        return False
    else:
        return True


if __name__ == "__main__":
    UDPServerSocket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    UDPServerSocket.bind(("127.0.0.1", 7735))
    true_data_indicator_value = b"0101010101010101"
    expected_sequence_number = 0
    ack = 0
    p = 0.05
    while True:
        bytes_received = UDPServerSocket.recvfrom(2048)
        message = bytes_received[0]
        client_address = bytes_received[1]
        # First 64 bits are always the header
        header = message[:64]
        data = message[64:]
        # First 32 bit are always the sequence number
        sequence_number = header[:32]
        # Next 16 bits are always the checksum
        checksum = header[32:48]
        # Next 16 bits are always the data indicator
        data_indicator = header[48:]
        # First check if this is a data packet
        if data_indicator == true_data_indicator_value:
            # Next verify the checksum
            if verify_checksum(checksum, data):
                # Next verify if the sequence number of the packet is correct
                if expected_sequence_number == int(sequence_number, 2):
                    # Next use the probability function to force some errors:
                    if check_probability(p):
                        # Everything is correct write this to the file
                        write_file(data)
                        # Set the new expected sequence number
                        expected_sequence_number += len(data)
                        # Set the ack number
                        ack = sequence_number
                        ack_segment = create_segment(ack)
                        UDPServerSocket.sendto(ack_segment, client_address)
                    else:
                        print("Packet Loss, sequence number = {}".format(int(sequence_number, 2)))
                else:
                    print(
                        "Packet dropped cause sequence number out of order. Expected sequence number {}. Received "
                        "sequence number {}".format(expected_sequence_number, int(sequence_number, 2)))
            else:
                print("Packet dropped cause checksum error.")
        else:
            print("Packet dropped cause of data indicator error.")