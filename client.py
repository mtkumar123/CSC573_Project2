import sys
import socket
import threading
import time

segments = []
time_stamp = []
close_flag = False

def rdt_send(filename, position, mss):
    """
    This function will read mss byte from the specified file, and return the byte and the current position in the file
    :param filename: file to read from
    :param position: the last known position of data read from the file
    :return: data, new_position
    """
    with open(filename, "rb") as f:
        f.seek(position, 0)
        data = f.read(mss)
        new_position = f.tell()
        if new_position == position:
            # If the new position is equal to the old position, that means we have come to the end of the file
            end_file_flag = True
        else:
            end_file_flag = False
    return data, new_position, end_file_flag


def carry_around_add(a, b):
    c = a + b
    return (c & 0xffff) + (c >> 16)


def calculate_checksum(data):
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
    return ~s & 0xffff


def create_segment(sequence_number, data):
    checksum = '{0:016b}'.format(calculate_checksum(data)).encode()
    data_indicator = b"0101010101010101"
    sequence_number = '{0:032b}'.format(sequence_number).encode()
    header = sequence_number + checksum + data_indicator
    segment = header + data
    return segment


def check_ack(ack):
    # Check the sequence number of the first packet in the segments list
    segment = segments[0]
    header = segment[:64]
    true_ack = header[:32]
    if ack == true_ack:
        return True
    else:
        return False


def get_sequence_number(segment):
    # Get the sequence number of a segment converted to int
    header = segment[:64]
    sequence_number = header[:32]
    sequence_number = int(sequence_number, 2)
    return sequence_number


def resend_segments(UDPClientSocket):
    # Resend all segments and add the new timestamp values
    global segments
    global time_stamp
    time_stamp = []
    for segment in segments:
        # Resend all the segments in the window
        UDPClientSocket.sendto(segment, (server_host_name, server_port))
        # Add new timestamps for each segment sent
        print("Retransmission sequence number = {}".format(get_sequence_number(segment)))
    time_stamp.append(time.time())


def sending_thread(UDPClientSocket, server_host_name, server_port, file_name, window_size, mss, condition):
    global segments
    global time_stamp
    global close_flag
    # Start off with position=0
    position = 0
    total_data = b""
    end_file_flag = False
    sequence_number = 0
    timeout_value = 1
    while end_file_flag is False:
        # Check if the len of segments is less than the window size
        if len(segments) < window_size:
            while len(total_data) < mss and end_file_flag is False:
                # Read mss bytes from the file
                data, position, end_file_flag = rdt_send(file_name, position, mss)
                total_data = total_data + data
            # Give control to the sender_thread, since segments is a global variable
            condition.acquire()
            # print("Control Acquired Thread One")
            segments.append(create_segment(sequence_number, total_data))
            condition.release()
            # send the most recently added segment from the segments list that's why we are using -1 for slicing
            # here
            UDPClientSocket.sendto(segments[-1], (server_host_name, server_port))
            # Add the timestamp of when this segment is being sent
            condition.acquire()
            if not time_stamp:
                time_stamp.append(time.time())
            condition.release()
            # print("Packet has been sent")
            condition.acquire()
            # print("Checking for timeouts while the window has still not become full")
            if (time.time() - time_stamp[0]) > timeout_value:
                print("Timeout, sequence number = {}".format(get_sequence_number(segments[0])))
                resend_segments(UDPClientSocket)
            condition.release()
            time.sleep(0.1)
        else:
            # window size exceeded, wait for some acknowledgements
            # print("Window size exceeded waiting for some time")
            condition.acquire()
            # Since window size has exceeded, we need to block on this thread for a time period equal to the
            # remaining time in the timeout_value =  timeout_value - (time.time() - time_stamp[0]))
            condition.wait(min(0, (timeout_value - (time.time() - time_stamp[0]))))
            # When control returns to thread 1 either cause of timeout value or cause thread 2 received an ack
            # we check to make sure the oldest timer does not exceed the timeout_value
            # if it does we enter the loop
            # print("Checking for timeouts while the window is full")
            if (time.time() - time_stamp[0]) > timeout_value:
                print("Timeout, sequence number = {}".format(get_sequence_number(segments[0])))
                resend_segments(UDPClientSocket)
                condition.wait(timeout_value)
            condition.release()
        # position can be used to determine the sequence number
        sequence_number = position
        total_data = b""
    # Exiting out of the first while loop means all the segments have been sent. However we still have to verify if
    # all the segments made it to their destination. This will be if there are still a segment left in the segments
    # list. Since the receiving thread pops out segments from the segments list whenever a segment gets acked
    while len(segments) != 0:
        # Now we just have to keep an eye on the timer, and retransmit if the timer for the oldest segment expires.
        condition.acquire()
        # print("Checking for timeouts after all the packets have been sent")
        if len(segments) != 0:
            if (time.time() - time_stamp[0]) > timeout_value:
                print("Timeout, sequence number = {}".format(get_sequence_number(segments[0])))
                resend_segments(UDPClientSocket)
                condition.wait(timeout_value)
            condition.release()
    # Here we can assume all the packets have been sent, and it is time to close the connection
    close_flag = True


def receiving_thread(UDPClientSocket, condition):
    global segments
    global time_stamp
    # To ensure the sending thread sends first
    time.sleep(0.1)
    while not close_flag:
        # print("Receiving an ACK")
        data = UDPClientSocket.recvfrom(2048)[0]
        # print("Ack Received")
        ack = data[:32]
        ack_indicator = data[48:]
        true_ack_indicator = b"1010101010101010"
        if true_ack_indicator == ack_indicator:
            # Verified this is an ack packet
            if check_ack(ack):
                condition.acquire()
                # print("Control Acquired Thread 2")
                print("Ack Received Popping segment from segments list")
                segments.pop(0)
                time_stamp[0] = time.time()
                last_ack = ack
                condition.notify()
                condition.release()
                # To ensure control goes back to thread 1
                time.sleep(0.1)


if __name__ == "__main__":
    """
    Accept command line parameters. First should server hostname/ip address, server port, filename, windowsize, and MSS
    """
    server_host_name = sys.argv[1]
    server_port = int(sys.argv[2])
    file_name = sys.argv[3]
    window_size = int(sys.argv[4])
    mss = int(sys.argv[5])
    UDPClientSocket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)

    condition = threading.Condition()
    sender_thread = threading.Thread(target=sending_thread,
                                     args=(UDPClientSocket, server_host_name, server_port, file_name, window_size, mss,
                                           condition))
    receiver_thread = threading.Thread(target=receiving_thread, args=(UDPClientSocket, condition))
    print(time.time())
    sender_thread.start()
    receiver_thread.start()
    sender_thread.join()
    receiver_thread.join()
    print(time.time())
    UDPClientSocket.close()
