import pytest

from golf.data.fit import read_fit

import fitbuild as fb


def write(tmp_path, content, name="a.fit"):
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_numbers_and_strings_of_a_message_are_read(tmp_path):
    chunk = fb.message(190, [(0, "uint32", 28390), (1, "string", b"Golf Example\x00\x00\x00\x00"), (5, "sint16", -12), (6, "uint8", 7)])
    messages = read_fit(write(tmp_path, fb.fit_file(chunk)))
    assert len(messages) == 1 and messages[0].number == 190
    assert messages[0].fields == {0: 28390, 1: "Golf Example", 5: -12, 6: 7}


def test_negative_coordinates_keep_their_sign(tmp_path):
    messages = read_fit(write(tmp_path, fb.fit_file(fb.message(194, [(2, "sint32", -562578001), (3, "sint32", 98027737)]))))
    assert messages[0].fields == {2: -562578001, 3: 98027737}


def test_several_data_messages_share_one_definition(tmp_path):
    fields = [(0, "uint8", 1), (2, "uint8", 4)]
    content = fb.fit_file(fb.message(193, fields, local=2), fb.data_only([(0, "uint8", 2), (2, "uint8", 5)], local=2),
                          fb.data_only([(0, "uint8", 3), (2, "uint8", 3)], local=2))
    assert [(m.fields[0], m.fields[2]) for m in read_fit(write(tmp_path, content))] == [(1, 4), (2, 5), (3, 3)]


def test_different_message_types_use_their_own_definitions(tmp_path):
    content = fb.fit_file(fb.message(190, [(0, "uint32", 1)], local=0), fb.message(193, [(0, "uint8", 9)], local=1),
                          fb.data_only([(0, "uint32", 2)], local=0))
    assert [(m.number, m.fields[0]) for m in read_fit(write(tmp_path, content))] == [(190, 1), (193, 9), (190, 2)]


def test_big_endian_files_are_read(tmp_path):
    messages = read_fit(write(tmp_path, fb.fit_file(fb.message(190, [(0, "uint32", 258), (1, "uint16", 513)], big=True))))
    assert messages[0].fields == {0: 258, 1: 513}


def test_arrays_come_back_as_tuples(tmp_path):
    messages = read_fit(write(tmp_path, fb.fit_file(fb.message(190, [(0, "array:uint16", [1, 2, 3])]))))
    assert messages[0].fields[0] == (1, 2, 3)


def test_developer_fields_are_skipped_without_losing_the_position(tmp_path):
    content = fb.fit_file(fb.message(190, [(0, "uint8", 5)], developer=[(0, 3)]), fb.message(193, [(0, "uint8", 6)], local=1))
    assert [(m.number, m.fields) for m in read_fit(write(tmp_path, content))] == [(190, {0: 5}), (193, {0: 6})]


def test_a_compressed_timestamp_header_is_a_data_message(tmp_path):
    compressed = bytes([0x80 | (1 << 5) | 3]) + b"\x07"                          # compressed header for local type 1, then its value
    content = fb.fit_file(fb.message(190, [(0, "uint8", 5)], local=1), compressed)
    assert [m.fields[0] for m in read_fit(write(tmp_path, content))] == [5, 7]


def test_a_twelve_byte_header_is_fine(tmp_path):
    assert read_fit(write(tmp_path, fb.fit_file(fb.message(190, [(0, "uint8", 5)]), header_size=12)))[0].fields == {0: 5}


def test_golf_file_builder_round_trips(tmp_path):
    messages = read_fit(write(tmp_path, fb.golf_fit("Golf Beispiel ~ Platz", [(4, 3), (3, 15), (5, 1)])))
    assert messages[0].fields[1] == "Golf Beispiel ~ Platz"
    assert [(m.fields[0], m.fields[2], m.fields[3]) for m in messages[1:]] == [(1, 4, 3), (2, 3, 15), (3, 5, 1)]


def test_something_that_is_not_a_fit_file_is_refused(tmp_path):
    with pytest.raises(ValueError, match="not a FIT file"):
        read_fit(write(tmp_path, b"this is not a fit file at all"))


def test_a_data_message_without_a_definition_is_refused(tmp_path):
    with pytest.raises(ValueError, match="undefined type"):
        read_fit(write(tmp_path, fb.fit_file(fb.data_only([(0, "uint8", 1)], local=3))))
