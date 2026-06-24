"""
Code to convert and aggregate all files in the input dirctory into the aggregated file
This is based on file_to_aggregate.py written by Joshua Hampton but opens the aggregate file once,
writes the global data and then for each input file, uses the conversion to ODIM code and writes that
dataset into the aggregate file

Author: Julia Crook
Date Created: 9 July 2025
Institution: CEMAC
             University of Leeds

open aggregate file and add contents from all files in input_dir
"""

import h5py
import numpy as np
import ast
import sys
from collections import Counter
from datetime import datetime
import glob
from dualpol import *
from typing import Optional

# function to check that top level how what and where attributes in a single pulse_mode time_group match
def check_attrs_match(attrs1, attrs2, wwh, exclude=[]):
    all_match = True
    for att in attrs1.keys():
        if att not in exclude:
            if att in attrs2.keys():
                if isinstance(attrs1[att], np.float64):
                    if attrs1[att] != 0:
                        mismatch_value = abs((attrs1[att] - attrs2[att]) / attrs1[att]) > 0.01
                    else:
                        mismatch_value = attrs2[att] != 0
                else:
                    mismatch_value = attrs1[att] != attrs2[att]
                if mismatch_value:
                    all_match = False
                    print(wwh, 'attr=', att, 'mismatching values', attrs1[att], attrs2[att], file=sys.stderr)
            else:
                all_match = False
                print(wwh, 'attr=', att, 'in group1 but not in group2', file=sys.stderr)
    for att in attrs2.keys():
        # if att is in both we have already checked the value above
        if att not in exclude and att not in attrs1.keys():
            all_match = False
            print(wwh, 'attr=', att, 'in group2 but not in group1', file=sys.stderr)
    return all_match
#------------------------------------------------------------------
# get the time_group, pulse_group and beam_number from the filename
# and put them in the arrays at index i
# inputs:
#    inputfile - the filename (full pathname)
#    i - the index into the time_groups, pulse_groups and beam_numbers for this file
#    time_groups - array of strings with the time_group that each file belongs to
#    pulse_group - array of strings with the pulse_group that each file belongs to
#    beam_numbers - array of ints with the beam_number for each file
#------------------------------------------------------------------
def get_file_info(inputfile, i, time_groups, pulse_groups, beam_numbers):
    # inputfile is of format <path>/metoffice-c-band-rain-radar_<radar>_YYYYmmddHHMM_raw-dual-polar-aug<zdr/ldr>-<pulse_group>-el<beam_number>.dat.gz

    filename=inputfile.split('/')[-1] # remove the path
    splits=filename.split('_')
    datetime=splits[2]
    file_hours=int(datetime[8:10])
    file_minutes=int(datetime[10:12])
    file_time=datetime[8:]
    splits2=splits[3].split('-') # split up latter part by -
    zdr_or_ldr=splits2[3]
    pulse_group=splits2[4] # should be lp or sp
    if pulse_group == 'lp':
        if 'ldr' in zdr_or_ldr:
            pulse_group = 'ldr'
            time_group = file_time # is there only one scan?
            delta_minutes=0
        else:
            delta_minutes=5 # all sweeps are done every 5 minutes
    elif pulse_group == 'sp':
        delta_minutes=10 # all sweeps are done every 10 minutes
    else:
        msg = f'Unrecognized pulse type - {pulse_type}'
        raise ValueError(msg)

    pulse_groups[i]=pulse_group
    beam_numbers[i]=int(splits2[5][2])
    check_previous=False
    pix=np.where(pulse_groups==pulse_group)
    time_groups_in_pulse_group=time_groups[pix]
    beam_numbers_in_pulse_group=beam_numbers[pix]
    if delta_minutes>0 and len(pix[0])>0:
        group_minutes=file_minutes - (file_minutes % delta_minutes)
        time_group = '{h:02d}{m:02d}'.format(h=file_hours,m=group_minutes)
        check_previous = (file_minutes % delta_minutes == 0)
        if i==0 or time_group==time_groups_in_pulse_group[0]:
            check_previous=False # there is no previous
        if check_previous:
            prev_hours=file_hours
            prev_minutes=group_minutes-delta_minutes
            if prev_minutes<0:
                prev_hours-=1
                prev_minutes=60+prev_minutes
            prev_time_group='{h:02d}{m:02d}'.format(h=prev_hours,m=prev_minutes)
            # check to see if the beam number of this scan appears in the previous time group,
            # and adjust time_group if needed
            # find the beam numbers that are in previous time group
            ix=np.where(time_groups_in_pulse_group==prev_time_group)
            prev_beams=beam_numbers_in_pulse_group[ix]
            if beam_numbers[i] not in prev_beams:
                #print(filename, pulse_group, f'time group changed from {time_group} to {prev_time_group} for beam {beam_numbers[i]}')
                time_group = prev_time_group

    time_groups[i]=time_group

    
# add the contents of a single file to aggregated file in given pulse group and time group as dataset_number
def _beam_counts(beam_number_array):
    return Counter(int(beam_number) for beam_number in beam_number_array)


def _format_beam_counts(counts):
    return '{' + ', '.join(f'{beam}: {counts[beam]}' for beam in sorted(counts)) + '}'


def _beam_set_matches(expected_beam_numbers, observed_beam_numbers):
    expected_counts = _beam_counts(expected_beam_numbers)
    observed_counts = _beam_counts(observed_beam_numbers)
    if observed_counts == expected_counts:
        return True, ''

    all_beams = sorted(set(expected_counts) | set(observed_counts))
    missing = [
        beam
        for beam in all_beams
        if observed_counts.get(beam, 0) < expected_counts.get(beam, 0)
    ]
    extra = [
        beam
        for beam in all_beams
        if expected_counts.get(beam, 0) == 0 and observed_counts.get(beam, 0) > 0
    ]
    duplicates = [
        beam
        for beam in all_beams
        if expected_counts.get(beam, 0) > 0
        and observed_counts.get(beam, 0) > expected_counts.get(beam, 0)
    ]
    parts = [
        f'expected {_format_beam_counts(expected_counts)}',
        f'observed {_format_beam_counts(observed_counts)}',
    ]
    if missing:
        parts.append(f'missing beams {missing}')
    if extra:
        parts.append(f'extra beams {extra}')
    if duplicates:
        parts.append(f'duplicate beams {duplicates}')
    return False, '; '.join(parts)


def _next_available_dataset_number(time_group_obj):
    existing = []
    for key in time_group_obj.keys():
        if key.startswith('dataset'):
            try:
                existing.append(int(key.replace('dataset', '')))
            except ValueError:
                continue
    return max(existing) + 1 if existing else 1


def _remove_time_group(day_f, pulse_group, time_group):
    if pulse_group in day_f.keys() and time_group in day_f[pulse_group].keys():
        del day_f[pulse_group][time_group]


def _read_single_site(inputfile):
    try:
        rad_file = SingleSite(inputfile)
    except Exception as exc:
        print(f"SKIP: {type(exc).__name__} in SingleSite for {inputfile}: {exc}", file=sys.stderr)
        return None

    if rad_file.number_of_volumes != 1:
        print(f"SKIP: number_of_volumes={rad_file.number_of_volumes} for {inputfile}", file=sys.stderr)
        return None

    return rad_file


def aggregate_file(inputfile, pulse_group, time_group, dataset_number, day_f, rad_file=None) -> Optional[int]:
    #print(inputfile.split('/')[-1], 'in time', time_group)
    # read input file as SingleSite object unless the caller has already validated it
    if rad_file is None:
        rad_file = _read_single_site(inputfile)
        if rad_file is None:
            return None

    if pulse_group not in day_f.keys():
        day_f.create_group(pulse_group)
        
    this_elangle=(rad_file.scan_stop_elevation + rad_file.scan_start_elevation) / 2.
    if time_group not in day_f[pulse_group].keys():
        day_f[pulse_group].create_group(time_group)
        day_f[pulse_group][time_group].attrs['Conventions'] = "ODIM_H5/V2_4"
        # create what where and how for this time
        # most what attributes are as for the individual file top level what, but time will be different in each sweep
        # we'll keep the first time
        rad_file.to_ODIM_top_level_what(day_f[pulse_group][time_group])
        # overwrite SCAN with PVOL as this will contain several scans in different datasets
        day_f[pulse_group][time_group]['what'].attrs['object'] = 'PVOL'

        # all where attributes are the same for this pulse and time group
        rad_file.to_ODIM_top_level_where(day_f[pulse_group][time_group])
        # add this elangle
        day_f[pulse_group][time_group]['where'].attrs['elangles_map'] = str({f'dataset{dataset_number}': this_elangle})

        # for now write the top level how for this file to top level how for this time group
        # not all attributes will be the same for all files in a time group - still need to check with ODIM specs
        rad_file.to_ODIM_top_level_how(day_f[pulse_group][time_group])
    else:
        # time group already exists
        if f'dataset{dataset_number}' in day_f[pulse_group][time_group]:
            new_dataset_number = _next_available_dataset_number(day_f[pulse_group][time_group])
            print(
                f"WARN: dataset{dataset_number} already exists for {pulse_group}/{time_group}; "
                f"using dataset{new_dataset_number} for {inputfile}",
                file=sys.stderr,
            )
            dataset_number = new_dataset_number

        this_what_attrs = rad_file.get_top_level_what_attrs()
        check_attrs_match(day_f[pulse_group][time_group]['what'].attrs, this_what_attrs, 'what', exclude=['object', 'time'])
        this_where_attrs = rad_file.get_top_level_where_attrs()
        check_attrs_match(day_f[pulse_group][time_group]['where'].attrs, this_where_attrs, 'where', exclude=['elangles_map'])
        this_how_attrs = rad_file.get_top_level_how_attrs()
        check_attrs_match(
            day_f[pulse_group][time_group]['how'].attrs,
            this_how_attrs,
            'how',
            exclude=['scan_count', 'RXlossH', 'RXlossV'],
        )
        this_how_quality_attrs = rad_file.get_top_level_how_quality_attrs()
        check_attrs_match(
            day_f[pulse_group][time_group]['how']['quality'].attrs,
            this_how_quality_attrs,
            'how.quality',
            exclude=[],
        )
        # check if this time is earlier
        this_file_time=rad_file.get_file_time_str(with_seconds=True)
        if int(this_file_time)<int(day_f[pulse_group][time_group]['what'].attrs['time']):
            day_f[pulse_group][time_group]['what'].attrs['time'] = this_file_time
            
        # add this elangle into map - but keep the datasets in order
        current_elangles = ast.literal_eval(day_f[pulse_group][time_group]['where'].attrs['elangles_map'])
        keys=np.asarray([key for key in current_elangles.keys()])
        keys=np.sort(keys)
        current_elangles=list(current_elangles.items()) # turn into a list so we can add dataset at a fixed position
        ix=np.where(keys>f'dataset{dataset_number}')
        this_tuple=(f'dataset{dataset_number}', this_elangle)
        if len(ix[0])==0:
            # none greater so add it to the end
            current_elangles.append(this_tuple)
        else:
            # add at postion ix[0][0]
            current_elangles.insert(ix[0][0], this_tuple)
        # turn back into a dictionary
        current_elangles = dict(current_elangles)
        day_f[pulse_group][time_group]['where'].attrs['elangles_map'] = str(current_elangles)
            
    # create the new dataset for this file
    if f'dataset{dataset_number}' in day_f[pulse_group][time_group]:
        new_dataset_number = _next_available_dataset_number(day_f[pulse_group][time_group])
        print(
            f"WARN: dataset{dataset_number} already exists for {pulse_group}/{time_group}; "
            f"using dataset{new_dataset_number} for {inputfile}",
            file=sys.stderr,
        )
        dataset_number = new_dataset_number

    day_f[pulse_group][time_group].create_group(f'dataset{dataset_number}')
    # save original file name as attribute in new file
    day_f[pulse_group][time_group][f'dataset{dataset_number}'].attrs['original_filename'] = inputfile.split('/')[-1]
    # convert current file to ODIM
    try:
        rad_file.to_ODIM_dataset(day_f[pulse_group][time_group][f'dataset{dataset_number}'])
    except Exception as exc:
        print(f"SKIP: {type(exc).__name__} writing dataset for {inputfile}: {exc}", file=sys.stderr)
        del day_f[pulse_group][time_group][f'dataset{dataset_number}']
        return None
    return dataset_number

#########################################
if len(sys.argv)<3:
    print('useage: ', sys.argv[0], '<inputdir> <output_file> <radar>')
    raise ValueError("invalid input")
    
inputdir = sys.argv[1]
output_file = sys.argv[2]
# which radar
radar_location = sys.argv[3]
#########################################

# select all .gz files available in the directory
file_list = glob.glob(inputdir+'/*.gz')
nfiles=len(file_list)
print(nfiles, 'files to convert in', inputdir)
if nfiles==0:
    raise Exception('No files to convert')
# sort to get in time order
file_list=np.sort(file_list)
# work out which time group and pulse_group each belongs to
time_groups=np.asarray(["xxxx"]*nfiles)
pulse_groups=np.asarray(["xxx"]*nfiles)
beam_numbers=np.zeros(nfiles, int)
[get_file_info(file_list[i], i, time_groups, pulse_groups, beam_numbers) for i in range(nfiles)]

# open the aggregated file
day_f = h5py.File(f"{output_file}", "w")

# create the global attributes and groups
day_f.attrs['Conventions'] = 'ODIM_H5/V2_4'
day_f.create_group('what')
day_f['what'].attrs['title'] = f'{radar_location} Single Site Data'
day_f['what'].attrs['product'] = 'SCAN: A scan of polar data'
day_f['what'].attrs['object'] = 'PVOL'
day_f['what'].attrs['comment'] = f'aggregated data from /ceda/badc/ukmo-nimrod/data/single-site/{radar_location}/raw-dual-polar/ metoffice-c-band-rain-radar.'
        
day_f.create_group('how')
day_f['how'].attrs['created'] = datetime.now().strftime('%Y%m%dT%H%M%S')
day_f['how'].attrs['creator_name'] = 'NCAS, Leeds'
day_f['how'].attrs['history'] = '/ceda/badc/ukmo-nimrod/data/single-site data converted to ODIM and aggregated into one file'
day_f['how'].attrs['institution'] = 'NCAS, Leeds'
day_f['how'].attrs['licence'] = 'http://artefacts.ceda.ac.uk/licences/specific_licences/nerc-met-office_agreement.pdf'
day_f['how'].attrs['processing_software'] = 'Nimrod2ODIM and convert_and_aggregate'
day_f['how'].attrs['processing_software_version'] = 'v1.0'
day_f['how'].attrs['project_principle_investigator'] = 'Met Office'
day_f['how'].attrs['project_principle_investigator_contact'] = 'enquiries@metoffice.gov.uk'
day_f['how'].attrs['references'] = 'https://github.com/cemac/Nimrod_convert_and_aggregate'

# handle the files by pulse group and then time group so we can work out the dataset number more easily
# as reading the files even sorted does not always give the different elevation angles in the same order
unique_pulse_groups=np.unique(pulse_groups)
for p in unique_pulse_groups:
    pix=np.where(pulse_groups==p)
    unique_beam_numbers=np.unique(beam_numbers[pix])
    beam_order={int(beam_number): bix for bix, beam_number in enumerate(unique_beam_numbers)}
    unique_time_groups=np.unique(time_groups[pix])
    print(len(unique_time_groups), 'time groups for', p)
    for t in unique_time_groups:
        fix=np.where((pulse_groups==p) & (time_groups==t))
        these_files=file_list[fix]
        this_nfiles=len(these_files)
        # check we have all the beams expected for this pulse type
        these_beam_numbers=beam_numbers[fix]
        beam_set_ok, beam_set_reason = _beam_set_matches(unique_beam_numbers, these_beam_numbers)
        if p in ['lp', 'sp'] and not beam_set_ok:
            print(
                f'SKIP: incomplete beam set for pulse and time {p} {t}; '
                f'{beam_set_reason}; no aggregate group written',
                file=sys.stderr,
            )
            continue
        elif not beam_set_ok:
            print(
                f'Warning! unexpected beam numbers for pulse and time {p} {t}; '
                f'{beam_set_reason}',
                file=sys.stderr,
            )

        sort_ix=np.asarray(
            sorted(
                range(this_nfiles),
                key=lambda ix: (beam_order.get(int(these_beam_numbers[ix]), this_nfiles), ix),
            )
        )
        these_files=these_files[sort_ix]
        these_beam_numbers=these_beam_numbers[sort_ix]

        rad_files=[]
        invalid_files=[]
        for f in range(this_nfiles):
            rad_file = _read_single_site(these_files[f])
            if rad_file is None:
                invalid_files.append(these_files[f])
            else:
                rad_files.append(rad_file)
        if len(invalid_files)>0:
            print(
                f'SKIP: invalid scans for pulse and time {p} {t}; '
                f'{len(invalid_files)} of {this_nfiles} scans failed validation; '
                f'no aggregate group written',
                file=sys.stderr,
            )
            continue

        # work out the order in which the scans in this time group happened to assign scan_index
        startepochs=[]
        dataset_nums=[]
        successful_files=[]
        write_failed=False
        try:
            for f in range(this_nfiles):
                dataset_number = f+1
                dataset_number = aggregate_file(these_files[f], p, t, dataset_number, day_f, rad_files[f])
                if dataset_number is None:
                    write_failed=True
                    break
                startepochs.append(day_f[p][t][f'dataset{dataset_number}']['how'].attrs['startepochs'])
                dataset_nums.append(dataset_number)
                successful_files.append(these_files[f])
        except Exception as exc:
            print(
                f'SKIP: {type(exc).__name__} writing pulse and time {p} {t}: {exc}; '
                f'rolling back aggregate group',
                file=sys.stderr,
            )
            write_failed=True

        expected_dataset_nums=list(range(1, this_nfiles+1))
        if write_failed or dataset_nums != expected_dataset_nums:
            if not write_failed:
                print(
                    f'SKIP: non-contiguous dataset numbers for pulse and time {p} {t}; '
                    f'expected {expected_dataset_nums}, got {dataset_nums}; '
                    f'rolling back aggregate group',
                    file=sys.stderr,
                )
            _remove_time_group(day_f, p, t)
            continue
        # now we have all scans for this time we can order them by startepoch
        sorted_ix=np.argsort(startepochs)
        for f in range(len(dataset_nums)):
            dataset_number=dataset_nums[f]
            scan_index=sorted_ix[f]+1
            day_f[p][t][f'dataset{dataset_number}']['how'].attrs['scan_index']=scan_index
            print(successful_files[f].split('/')[-1], 'in time', t, 'dataset', dataset_number, 'scan_index', scan_index, 'pulse width', day_f[p][t]['how'].attrs['pulsewidth'], 'unambig vel', day_f[p][t]['how'].attrs['NI'], 'rscale', day_f[p][t][f'dataset{dataset_number}']['where'].attrs['rscale'], 'rstart', day_f[p][t][f'dataset{dataset_number}']['where'].attrs['rstart'])
        # and we can update the scan count
        day_f[p][t]['how'].attrs['scan_count']=len(dataset_nums)
            
# close the file
day_f.close()
exit(0)
