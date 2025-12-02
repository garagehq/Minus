# Ad Detection Datasets for Fine-Tuning

This document catalogs datasets suitable for fine-tuning a vision-language model to detect advertisements vs. regular content.        

---

## Quick Summary

| Dataset | Size | Type | Availability | Best For |
|---------|------|------|--------------|----------|
| **SponsorBlock** | 30K+ videos, millions of frames | Video frames | Open (CC BY-NC-SA 4.0) | YouTube sponsored segments |
| **PITT Ads Dataset** | 64,832 images + 3,477 videos | Images/Video | Email request required | General ad understanding |
| **AdImageNet** | 9,003 images (19K full) | Banner ads | Hugging Face (free account) | Web banner ads |
| **UCI Internet Ads** | 3,279 instances | Feature vectors | Open (CC BY 4.0) | Web ad classification |
| **TV Commercial Dataset** | 130,000 instances | Audio-visual features | Open (CC BY 4.0) | TV commercial detection |
| **Ads-1k** | 1,041 videos | Video segments | Open (BSD-2) | Video ad editing |
| **Magazine Ad Dataset** | 3,885 images | Scanned pages | Not public (contact authors) | Print ad detection |

---

## Downloaded Training Data (Local)

The following datasets have been downloaded and extracted to the `training/data/` directory:

### PITT Ads Dataset (Downloaded)
**Location**: `training/data/pitt_ads/`

| Category | Count | Path |
|----------|-------|------|
| **Ad Images** | 64,832 | `training/data/pitt_ads/ads/` |
| **Non-Ad Images** | 13,593 | `training/data/pitt_ads/non_ads/` |
| **Total** | 78,425 | |

**Source**: Google Storage (publicly accessible)
- Subfolders 0-10: Ad images (~64K web ads)
- resnet_negative.zip: Non-ad images (ImageNet-style negatives)

**Status**: Ready for fine-tuning

### AdImageNet (Downloaded)
**Location**: `training/data/adimagenet/images/`

| Category | Count | Path |
|----------|-------|------|
| **Banner Ads** | 9,003 | `training/data/adimagenet/images/` |

**Source**: HuggingFace (`PeterBrendan/AdImageNet`)
- Various banner sizes: 300x250, 728x90, 970x250, etc.
- Includes OCR-extracted text metadata

**Status**: Ready for fine-tuning

### Combined Dataset Statistics

| Category | Train | Validation | Total |
|----------|-------|------------|-------|
| **PITT Ads** | ~58K | ~6.5K | 64,832 |
| **AdImageNet** | ~8.1K | ~0.9K | 9,003 |
| **Non-Ads** | 12,237 | 1,360 | 13,597 |
| **Total Ads** | 66,451 | 7,384 | 73,835 |
| **Total** | **78,688** | **8,744** | **87,432** |

---

## Recommended Datasets (Easiest to Access)

### 1. SponsorBlock Database
**Best for: YouTube sponsored content detection with video frames**

The crowdsourced database behind the SponsorBlock browser extension. Contains timestamps for sponsored segments in millions of YouTube videos.

- **Size**: 30,000+ labeled videos, ~33.6 million frames (1.5M positive labels)
- **Labels**: Sponsor segments with start/end timestamps
- **Format**: SQL database (CSV via sb-mirror)
- **License**: CC BY-NC-SA 4.0

**How to Use**:
1. Download via [sb-mirror](https://github.com/mchangrh/sb-mirror) (recommended)
2. Or access JSON API: `https://sponsor.ajay.app/database.json`    
3. Extract video frames at labeled timestamps using yt-dlp + ffmpeg

**Existing ML Projects Using This Data**:
- [DeepSponsorBlock](http://cs230.stanford.edu/projects_fall_2020/reports/55822706.pdf) - Stanford CS230 project using video frames   
- [SponsorBlock-ML](https://github.com/ajayyy/SponsorBlock/wiki/Dataset-Uses) - Multiple implementations listed
- [sponsor-block-subtitles-80k](https://www.kaggle.com/) - Kaggle dataset with 93.79% accuracy

**Links**:
- Database: https://sponsor.ajay.app/database
- Wiki: https://github.com/ajayyy/SponsorBlock/wiki/Dataset-Uses   
- Mirror tool: https://github.com/mchangrh/sb-mirror

---

### 2. AdImageNet (Hugging Face)
**Best for: Web banner/display ad detection**

A curated collection of programmatic ad creatives with extracted text.

- **Size**: 9,003 samples (full dataset 19K+)
- **Ad Sizes**: 300×250, 728×90, 970×250, 300×600, 160×600, etc.   
- **Format**: Parquet with images and metadata
- **License**: MIT
- **Text Extraction**: Via Google Vision API

**How to Download**:
```python
from datasets import load_dataset

# Requires Hugging Face account + agreement
dataset = load_dataset("PeterBrendan/AdImageNet")
```

**Links**:
- Dataset: https://huggingface.co/datasets/PeterBrendan/AdImageNet 
- Related text dataset: https://huggingface.co/datasets/PeterBrendan/Ads_Creative_Text_Programmatic

---

### 3. UCI TV News Commercial Detection Dataset
**Best for: TV commercial vs. regular content classification**     

Audio-visual features extracted from 150 hours of TV news broadcasts.

- **Size**: ~130,000 instances
- **Sources**: 5 channels (CNN IBN, NDTV 24X7, Times Now, BBC, CNN)
- **Resolution**: 720×576 at 25fps
- **Format**: CSV feature vectors
- **License**: CC BY 4.0

**Features Included**:
- **Audio**: Short-term energy, zero crossing rate, spectral centroid, spectral flux, MFCC
- **Visual**: Shot length, screen text distribution, motion distribution, frame difference, edge change ratio

**Links**:
- UCI Repository: https://archive.ics.uci.edu/dataset/326/tv+news+channel+commercial+detection+dataset
- Data cleaning tool: https://github.com/kramea/tv_commercial_data_cleaning

---

### 4. UCI Internet Advertisements Dataset
**Best for: Web page ad detection (feature-based)**

Classic dataset for predicting whether an image on a web page is an ad.

- **Size**: 3,279 instances, 1,558 features
- **Task**: Binary classification (ad vs. nonad)
- **Format**: CSV
- **License**: CC BY 4.0

**Features**: Image geometry, URL phrases, alt text, anchor text, nearby words

**Links**:
- UCI Repository: https://archive.ics.uci.edu/dataset/51/internet+advertisements
- Kaggle Mirror: https://www.kaggle.com/datasets/uciml/internet-advertisements-data-set

---

## Research Datasets (Require Contact/Registration)

### 5. PITT Ads Dataset (CVPR 2017)
**Best for: Comprehensive ad understanding with rich annotations** 

The largest academic ad image dataset with detailed annotations.   

- **Size**: 64,832 image ads + 3,477 video ads
- **Annotations**: Topic, sentiment, call-to-action, symbolic references
- **Format**: Images + JSON annotations

**How to Access**:
1. Download annotations directly from website
    - https://storage.googleapis.com/ads-dataset/subfolder-10.zip, https://storage.googleapis.com/ads-dataset/subfolder-9.zip, https://storage.googleapis.com/ads-dataset/subfolder-8.zip, https://storage.googleapis.com/ads-dataset/subfolder-7.zip, https://storage.googleapis.com/ads-dataset/subfolder-6.zip, https://storage.googleapis.com/ads-dataset/subfolder-5.zip , https://storage.googleapis.com/ads-dataset/subfolder-4.zip  , https://storage.googleapis.com/ads-dataset/subfolder-3.zip , https://storage.googleapis.com/ads-dataset/subfolder-2.zip , https://storage.googleapis.com/ads-dataset/subfolder-1.zip , https://storage.googleapis.com/ads-dataset/subfolder-0.zip  
2. Download the negatives (non ads)
    -  https://storage.googleapis.com/ads-dataset/resnet_negative.zip


**Research Using This Dataset**:
- [ADVISE Model](https://github.com/yekeren/ADVISE-Image_ads_understanding) - 69% accuracy on ad understanding
- Multiple CVPR/ECCV papers

**Links**:
- Project page: https://people.cs.pitt.edu/~kovashka/ads/
- Papers With Code: https://paperswithcode.com/dataset/image-and-video-advertisements
- Dataset loader: https://gist.github.com/kyamagu/0aa8c06501bd8a5816640639d4d33a17

---

### 6. Ads-1k Video Dataset
**Best for: Video advertisement segment analysis**

Dataset for ad video editing research with segment-level annotations.

- **Size**: 942 training + 99 test videos
- **Annotations**: Narrative techniques, segment coherence, duration
- **Features**: BERT text, Swin-Transformer visual, VGGish audio   
- **License**: BSD-2-Clause

**Links**:
- GitHub: https://github.com/yunlong10/Ads-1k
- Download: Google Drive / Baidu Netdisk (links in repo)

---

## Smaller/Specialized Datasets

### 7. ADS-16 Computational Advertising Dataset
- **Size**: 300 real ads rated by 120 people
- **Focus**: Ad effectiveness/perception
- **Link**: https://www.kaggle.com/datasets/groffo/ads16-dataset   

### 8. Advertisement Board Image Dataset
- **Focus**: Scene text recognition in outdoor ads
- **Link**: https://www.kaggle.com/datasets/dataclusterlabs/ad-board

### 9. Magazine Ad Dataset (Not Public)
- **Size**: 3,885 images (2,078 ads, 1,807 non-ads)
- **Sources**: Departures, Mechanical Engineering, Appliance Design, ASEE magazines
- **Accuracy achieved**: 78% with CNN
- **Paper**: https://www.mdpi.com/1099-4300/20/12/982
- **Access**: Contact paper authors


### Huggingface specific ad databases
Hugging Face Datasets

  | Dataset                                        | Size
                 | Description
        | URL
                            |
  |------------------------------------------------|-----------    
  ---------------|---------------------------------------------
  ------|------------------------------------------------------
  --------------------------|
  | PeterBrendan/AdImageNet                        | 9,003
  images (19K full)  | Programmatic ad banners with OCR text       
            |
  https://huggingface.co/datasets/PeterBrendan/AdImageNet
                    |
  | PeterBrendan/Ads_Creative_Ad_Copy_Programmatic | 7,097
  samples            | Ad creatives with text
            | https://huggingface.co/datasets/PeterBrendan/Ads_    
  Creative_Ad_Copy_Programmatic |
  | Xenova/sponsorblock                            | Large
  (transcript-based) | YouTube sponsor segment detection
            |
  https://huggingface.co/datasets/Xenova/sponsorblock
                    |
  | Xenova/sponsorblock-768                        | Processed     
  version        | Embedded sponsor segments
        |
  https://huggingface.co/datasets/Xenova/sponsorblock-768
                    |
  | webis/generative-native-ads                    | 32,206        
  samples           | Native ads in chatbot responses (binary      
  labeled)  |
  https://huggingface.co/datasets/webis/generative-native-ads      
                    |
  | biglam/illustrated_ads                         | 549 images    
                 | Historic newspaper ads (illustrated vs
  text-only) |
  https://huggingface.co/datasets/biglam/illustrated_ads
                    |
  | superfine/advertising-banner-generation        | 1,365
  images             | Ad banner images
            | https://huggingface.co/datasets/superfine/adverti    
  sing-banner-generation        |
  | 0x7o/ad_detector                               | 1K-10K        
  samples           | Text ad detection (Apache 2.0)
           | https://huggingface.co/datasets/0x7o/ad_detector      
                               |
  | christinacdl/clickbait_notclickbait_dataset    | Binary        
  labels            | Clickbait detection
           | https://huggingface.co/datasets/christinacdl/click    
  bait_notclickbait_dataset    |
  | llm-wizard/Product-Descriptions-and-Ads        | 100
  samples              | GPT-4 generated product ads
              | https://huggingface.co/datasets/llm-wizard/Prod    
  uct-Descriptions-and-Ads        |

  ---
  Roboflow Universe Datasets

  | Dataset                    | Size        | Description
                    | URL
                                      |
  |----------------------------|-------------|-----------------    
  ------------------|------------------------------------------    
  ------------------------------------|
  | advertisement-detection    | 501 images  | Instance
  segmentation, 45 classes | https://universe.roboflow.com/thar    
  indu-chamoda-boega/advertisement-detection |
  | advertising-banner-finder  | 52 images   | Banner detection    
   (YOLO format)    | https://universe.roboflow.com/project-t8m    
  ca/advertising-banner-finder        |
  | ads (AdBreaker)            | 85 images   | Ad detection        
                    |
  https://universe.roboflow.com/adbreaker/ads-hl6uc
                  |
  | Banner detection with YOLO | Pre-trained | Ready-to-use        
  model                | https://universe.roboflow.com/school-9    
  uzxn/banner-detection-with-yolo     
---

## DIY Dataset Creation Strategies

### Strategy 1: SponsorBlock + YouTube Frames
```bash
# 1. Get video IDs from SponsorBlock database
# 2. Download frames at specific timestamps
yt-dlp --write-info-json -o "%(id)s.%(ext)s" VIDEO_URL
ffmpeg -i video.mp4 -vf "fps=1" frames/%04d.jpg

# 3. Label frames based on timestamp ranges
# If timestamp in [sponsor_start, sponsor_end] → ad
# Otherwise → non-ad
```

### Strategy 2: Modified Ad Blocker
Use browser extension like uBlock Origin to:
1. Highlight detected ads with colored borders
2. Take screenshots
3. Build dataset over time browsing the web

### Strategy 3: Synthetic Generation (What we did)
1. Download stock photos (Lorem Picsum, Unsplash)
2. Add ad-style overlays: "SPONSORED", "AD", "Buy Now!", etc.      
3. Vary overlay style: banners, watermarks, corner badges


### Strategy 4: Mechanical Turk
---

## Fine-Tuning Considerations

### For SmolVLM/Small VLMs

**Recommended approach**:
1. Start with SponsorBlock video frames (millions of labeled examples)
2. Supplement with AdImageNet banner ads
3. Add synthetic overlays for variety

**Minimum dataset size**: 10,000+ images recommended for vision tasks

### Key Labels for Binary Classification
- `ad` / `is_ad` / `1` - Contains advertisement markers
- `non_ad` / `content` / `0` - Regular content

### What to Include in "Ad" Class
- Sponsored content markers ("SPONSORED", "AD", "#AD")
- Call-to-action overlays ("Buy Now", "Shop", "Click Here")        
- Brand promotional content
- Product placements with text
- Banner/display advertisements

### What to Include in "Non-Ad" Class
- Movie/TV stills
- YouTube video frames (non-sponsored segments)
- Stock photography
- News footage
- Documentary content

---

## Performance Benchmarks from Literature

| Method | Dataset | Accuracy | Notes |
|--------|---------|----------|-------|
| CNN (4 filters) | Magazine Ads | 78% | Grayscale 100×100 |       
| BERT text features | Ad Text | 96.7% | Text-only classification |
| Audio-Visual CNN | TV Commercial | 93.26% | Transfer learning |  
| SponsorBlock ML | YouTube | 93.79% | Transcript-based |
| ADVISE | PITT Ads | 69% | Symbolism understanding |

---



## Sources

- [SponsorBlock Wiki](https://github.com/ajayyy/SponsorBlock/wiki/Dataset-Uses)
- [PITT Ads Project](https://people.cs.pitt.edu/~kovashka/ads/)    
- [AdImageNet - Hugging Face](https://huggingface.co/datasets/PeterBrendan/AdImageNet)
- [UCI ML Repository](https://archive.ics.uci.edu/)
- [DeepSponsorBlock Paper](http://cs230.stanford.edu/projects_fall_2020/reports/55822706.pdf)
- [AD or Non-AD Paper](https://www.mdpi.com/1099-4300/20/12/982)   
- [Ads-1k GitHub](https://github.com/yunlong10/Ads-1k)

Here's what I found. Unfortunately, there's no single production-ready model
  specifically for visual ad detection, but there are several promising options:

  ---
  Most Promising Pre-trained Models

  | Project              | URL
             | Accuracy | Notes                                                    |
  |----------------------|------------------------------------------------------------    
  -----------|----------|----------------------------------------------------------|      
  | Percival             | https://github.com/dxaen/percival
             | 96.76%   | Brave browser's CNN ad blocker. Best documented.         |      
  | ad-versarial         | https://github.com/ftramer/ad-versarial
             | N/A      | Has pre-trained models in releases for Percival/Sentinel |      
  | Roboflow Banner YOLO |
  https://universe.roboflow.com/school-9uzxn/banner-detection-with-yolo | N/A      |      
  764 images + pre-trained YOLO model with API             |

  ---
  Research Papers (No Public Weights)

  | Paper                    | URL
                                                             | Architecture
       |
  |--------------------------|--------------------------------------------------------    
  -----------------------------------------------------------|------------------------    
  -----|
  | Ad-Net (TV commercials)  | https://arxiv.org/abs/1806.08612
                                                             | Two-stream audio-visual    
   CNN |
  | ADNet (video frames)     | https://arxiv.org/abs/1811.04115
                                                             | Deep CNN
       |
  | Amazon Ad Detection      | https://www.amazon.science/publications/a-deep-neural-f    
  ramework-to-detect-individual-advertisement-ad-from-videos | Deep NN + audio
       |
  | CNN Commercial Detection | https://dl.acm.org/doi/10.1145/3171592.3171619
                                                             | CNN + SVM (93%
  precision)   |
  | Magazine Ad Detection    | https://www.mdpi.com/1099-4300/20/12/982
                                                             | Simple CNN
       |

  ---
  Datasets for Training Your Own

  | Dataset                | URL
                         | Size                   |
  |------------------------|----------------------------------------------------------    
  -----------------------|------------------------|
  | AdImageNet             | https://huggingface.co/datasets/PeterBrendan/AdImageNet      
                         | 9,003 ad creatives     |
  | ad_detector            | https://huggingface.co/datasets/0x7o/ad_detector
                         | Ad detection specific  |
  | illustrated_ads        | https://huggingface.co/datasets/biglam/illustrated_ads   
                         | Historic newspaper ads |
  | Roboflow banner finder |
  https://universe.roboflow.com/project-t8mca/advertising-banner-finder/dataset/3 | 52    
   annotated banners   |
  | Kaggle ADS-16          | https://www.kaggle.com/datasets/groffo/ads16-dataset
                         | 300 real ads           |

  ---
  GitHub Repos Worth Investigating

  | Repo           | URL                                                       |
  Description                        |
  |----------------|-----------------------------------------------------------|------    
  ------------------------------|
  | Percival       | https://github.com/dxaen/percival                         |
  Brave's perceptual ad blocker      |
  | ad-versarial   | https://github.com/ftramer/ad-versarial                   |
  Pre-trained models in releases     |
  | ADVISE         | https://github.com/yekeren/ADVISE-Image_ads_understanding |
  InceptionV4-based ad understanding |
  | YOLOv3 OTT ads | https://github.com/debjitdbb/ad-detection-deep-learning   |
  Real-time OTT stream ad detection  |

  ---
  My Recommendation

  Start with Percival (https://github.com/dxaen/percival):
  - 96.76% accuracy on ad detection
  - Well-documented research paper: https://brave.com/research/files/atc20-din.pdf        
  - CNN-based, should be convertible to ONNX → RKNN
  - Pre-trained models mentioned, may be extractable from the ad-versarial releases       

  Backup option: Fine-tune MobileNetV2 or EfficientNet on the HuggingFace AdImageNet      
  dataset (9,003 samples). These lightweight architectures convert well to RKNN and       
  run fast on RK3588.

  
## Text Based Ads Classifier
https://huggingface.co/bondarchukb/bert-ads-classification