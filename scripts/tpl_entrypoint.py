import argparse


def main(performance_midi, mei_uri, structure_uri, performance_container, audio_container, webid):
    pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--performanceMidi')
    parser.add_argument('--meiUri')
    parser.add_argument('--structureUri')
    parser.add_argument('--performanceContainer')
    parser.add_argument('--audioContainer')
    parser.add_argument('--webId')

    args = parser.parse_args()
    main(args.performanceMidi, args.meiUri, args.structureUri, args.performanceContainer,
         args.audioContainer, args.webId)
