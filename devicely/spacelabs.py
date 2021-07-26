import csv
import datetime as dt
import random
from xml.etree import ElementTree as ET

import pandas as pd


class SpacelabsReader:
    """
    Parses, timeshifts, deidentifies and writes data
    generated by Spacelabs(SL90217).

    Attributes
    ----------
    data : DataFrame
        DataFrame with the values that were read from the abp file.

    subject : str
        Contains the sujbect's id. Can be changed for
        deidentification.

    valid_measurements : str
        Contains the number of valid measurements in the
        abp file.

    metadata : dict
        The measurements' metadata. Read from the xml at the bottom
        of the abp file. Can be erased for deidentification.
    """

    def __init__(self, path):
        """
        Reads the abp file generated by the Spacelabs device and saves the
        parsed DataFrame.

        Parameters
        ----------
        path : str
            Path of the abp file.
        """

        # Metadata Definition
        metadata = pd.read_csv(path, nrows=5, header=None)
        self.subject = str(metadata.loc[0, 0])
        base_date = dt.datetime.strptime(metadata.loc[2, 0], '%d.%m.%Y').date()
        if metadata.loc[4, 0] != 'Unknown Line':
            self.valid_measurements = str(metadata.loc[4, 0])
        else:
            metadata = pd.read_csv(path, nrows=6, header=None)
            self.valid_measurements = str(metadata.loc[5, 0])

        column_names = ['hour', 'minutes', 'SYS(mmHg)', 'DIA(mmHg)', 'ACC_x', 'ACC_y', 'error', 'ACC_z']
        self.data = pd.read_csv(path, sep=',', skiprows=51, skipfooter=1, header=None, names=column_names, engine='python')

        # Adjusting Date
        dates = [base_date]
        times = [dt.time(hour=self.data.loc[i, 'hour'], minute=self.data.loc[i, 'minutes']) for i in range(len(self.data))]
        current_date = base_date
        for i in range(1, len(times)):
            if times[i] < times[i-1]:
                current_date += dt.timedelta(days=1)
            dates.append(current_date)

        self.data.reset_index(inplace=True)
        self.data['timestamp'] = pd.to_datetime([dt.datetime.combine(dates[i], times[i]) for i in range(len(dates))])
        self.data['date'] = dates
        self.data['time'] = times

        order = ['timestamp', 'date', 'time', 'SYS(mmHg)', 'DIA(mmHg)', 'ACC_x', 'ACC_y', 'ACC_z', 'error']
        self.data = self.data[order]

        self._eb_dropped = False
        if (self.data['error'] != 'EB').all():
            self.data.set_index('timestamp', inplace=True)
            self._eb_dropped = True

        xml_line = open(path, 'r').readlines()[-1]
        xml_root = ET.fromstring(xml_line)
        self.metadata = self._etree_to_dict(xml_root)['XML']


    def deidentify(self, subject_id=None):
        """
        Deidentifies the data by removing the original XML metadata and
        subject id.

        Parameters
        ----------
        subject_id : str, optional
            New subject id to be written in the
            deidentified file, by default None.
        """
        # Changing subject id
        if subject_id:
            self.subject = subject_id
        else:
            self.subject = ''

        self.metadata = {
            'PATIENTINFO' : {'DOB' : '',
                             'RACE' : ''},
            'REPORTINFO' : {'PHYSICIAN' : '',
                            'NURSETECH' : '',
                            'STATUS' : '',
                            'CALIPERSUMMARY' : {'COUNT' : ''}}
        }

    def write(self, path):
        """
        Writes the signals and metadata to the
        writing path in the same format as it was read.

        Parameters
        ----------
        path : str
            Path to writing file. Writing mode: 'w'.
            Use the file extension 'abp' to keep the SpaceLabs standard.
        """

        with open(path, 'w') as f:
            f.write(f"\n{self.subject}")
            f.write(8 * '\n')
            f.write("0")
            f.write(8 * '\n')
            f.write(self.data.date[0].strftime("%d.%m.%Y"))
            f.write(7 * '\n')
            f.write("Unknown Line")
            f.write(26 * '\n')
            f.write(self.valid_measurements + "\n")
            printing_df = self.data.drop(columns=['date', 'time'])
            printing_df['hours'] = self.data.time.map(lambda x: x.strftime("%H"))
            printing_df['minutes'] = self.data.time.map(lambda x: x.strftime("%M"))
            order = ['hours', 'minutes', 'SYS(mmHg)', 'DIA(mmHg)', 'ACC_x', 'ACC_y', 'error', 'ACC_z']
            printing_df = printing_df[order]
            printing_df.fillna(-9999, inplace=True)
            printing_df.replace('EB', -9998, inplace=True)
            printing_df.replace('AB', -9997, inplace=True)
            printing_df[['SYS(mmHg)', 'DIA(mmHg)', 'ACC_x', 'ACC_y', 'error', 'ACC_z']] = printing_df[
                ['SYS(mmHg)', 'DIA(mmHg)', 'ACC_x', 'ACC_y', 'error', 'ACC_z']].astype(int).astype(str)
            printing_df.replace('-9999', '""', inplace=True)
            printing_df.replace('-9998', '"EB"', inplace=True)
            printing_df.replace('-9997', '"AB"', inplace=True)
            printing_df.to_csv(f, header=None, index=None, quoting=csv.QUOTE_NONE)

            xml_node = ET.Element('XML')
            xml_node.extend(self._dict_to_etree(self.metadata))
            xml_line = ET.tostring(xml_node, encoding="unicode")
            f.write(xml_line)
        
    def _etree_to_dict(self, etree_node):
        children = list(iter(etree_node))
        if len(children) == 0:
            return {etree_node.tag: etree_node.text}
        else:
            dict_ = dict()
            for child in children:
                dict_ = {**dict_, **self._etree_to_dict(child)}
            return {etree_node.tag: dict_}

    def _dict_to_etree(self, dict_):
        def rec(key, value):
            node = ET.Element(key)
            if isinstance(value, dict):
                for child_key in value:
                    node.append(rec(child_key, value[child_key]))
            else:
                node.text = str(value) if value else ''
            return node

        return [rec(k, v) for k, v in dict_.items()]

    def timeshift(self, shift='random'):
        """
        Timeshifts the data by shifting all time related columns.

        Parameters
        ----------
        shift : None/'random', pd.Timestamp or pd.Timedelta
            If shift is not specified, shifts the data by a random time interval
            between one month and two years to the past.

            If shift is a timdelta, shifts the data by that timedelta.

            If shift is a timestamp, shifts the data such that the earliest entry
            is at that timestamp and the remaining values keep the same time distance to the first entry.
        """

        if shift == 'random':
            one_month = pd.Timedelta('30 days').value
            two_years = pd.Timedelta('730 days').value
            random_timedelta = - pd.Timedelta(random.uniform(one_month, two_years)).round('min')
            self.timeshift(random_timedelta)

        if self._eb_dropped:
            if isinstance(shift, pd.Timestamp):
                timedeltas = self.data.index - self.data.index[0]
                self.data.index = shift.round('min') + timedeltas
            if isinstance(shift, pd.Timedelta):
                self.data.index += shift.round('min')
            self.data['date'] = self.data.index.map(lambda timestamp: timestamp.date())
            self.data['time'] = self.data.index.map(lambda timestamp: timestamp.time())
        else:
            if isinstance(shift, pd.Timestamp):
                timedeltas = self.data['timestamp'] - self.data['timestamp'].min()
                self.data['timestamp'] = shift.round('min') + timedeltas
            if isinstance(shift, pd.Timedelta):            
                self.data['timestamp'] += shift.round('min')
            self.data['date'] = self.data['timestamp'].map(lambda timestamp: timestamp.date())
            self.data['time'] = self.data['timestamp'].map(lambda timestamp: timestamp.time())


        if 'window_start' in self.data.columns and 'window_end' in self.data.columns:
            if isinstance(shift, pd.Timestamp):
                timedeltas = self.data['window_start'] - self.data['window_start'].min()
                self.data['window_start'] = shift.round('min') + timedeltas
                timedeltas = self.data['window_end'] - self.data['window_end'].min()
                self.data['window_end'] = shift.round('min') + timedeltas
            if isinstance(shift, pd.Timedelta):
                self.data['window_start'] += shift.round('min')
                self.data['window_end'] += shift.round('min')


    def drop_EB(self):
        """
        Drops all entries with "EB"-errors from the DataFrame

        Note
        ----------
        Before dropping, the dataframe has a range index because the timestamps
        might not be unique. After dropping, the timestamp column will be unique
        and is thus used as an index for easy indexing.
        """

        if not self._eb_dropped:
            self.data = self.data[self.data['error'] != 'EB']
            self.data.set_index('timestamp', inplace=True)
            self._eb_dropped = True

    def set_window(self, window_duration, window_type):
        """
        Set a window around, before or after the blood pressure measurement by
        creating two new columns with the window_start and window_end times.
        
        Parameters
        ----------
        window_duration: pd.Timedelta, datetime.timedelta
            Duration of the window.
        
        window_type: bffill, bfill, ffill
            Bffill stands for backward-forward fill. The window is defined as
            half after and half before the start of the measurement.
            Bfill stands for backward fill.
            The window is defined before the start of the measurement.
            Ffill stands for forward fill.
            The window is defined after the start of the measurement.
        """

        if self._eb_dropped:
            if window_type == 'bffill':
                self.data['window_start'] = self.data.index - window_duration // 2
                self.data['window_end'] = self.data.index + window_duration // 2
            elif window_type == 'bfill':
                self.data['window_start'] = self.data.index - window_duration
                self.data['window_end'] = self.data.index
            elif window_type == 'ffill':
                self.data['window_start'] = self.data.index
                self.data['window_end'] = self.data.index + window_duration
        else:
            if window_type == 'bffill':
                self.data['window_start'] = self.data['timestamp'] - window_duration // 2
                self.data['window_end'] = self.data['timestamp'] + window_duration // 2
            elif window_type == 'bfill':
                self.data['window_start'] = self.data['timestamp'] - window_duration
                self.data['window_end'] = self.data['timestamp']
            elif window_type == 'ffill':
                self.data['window_start'] = self.data['timestamp']
                self.data['window_end'] = self.data['timestamp'] + window_duration
