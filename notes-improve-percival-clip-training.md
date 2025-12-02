Original Training parameters:
cd /mnt/c/Users/cyeng/Documents/Projects/stream-sentry-overall/training        
python finetune_percival.py --epochs 10 --batch_size 32

#Fine-tune CLIP (larger, better generalization):
python finetune_clip.py --mode linear --epochs 5 --batch_size 64

Great question! Let me analyze the results and help you
  think through this.

  Analysis of Current Results

  The Good

  - TV dataset improved significantly - Both models went from     
  ~45% to 69%, showing fine-tuning worked
  - 100% recall on Percival - It's catching all the ads (no       
  false negatives)
  - 5ms latency on Percival - Blazing fast for real-time use      

  The Concerning

  - Low precision (54-67%) - Too many false positives
  (labeling non-ads as ads)
  - Web frames dropped for Percival (58% vs 69.5% baseline) -     
  Possible overfitting to TV-style ads
  - CLIP didn't improve as much as expected given 92.58%
  validation accuracy during training

  Root Cause: Severe Class Imbalance

  Your dataset has 78K ads vs 2K non-ads (39:1 ratio). This is    
   almost certainly the main issue:

  1. Model learns "just say ad" - With 97.5% of training data     
  being ads, predicting "ad" for everything gives 97.5%
  training accuracy
  2. 100% recall, low precision - Classic symptom of
  imbalanced data. Model catches all ads but also flags many      
  non-ads
  3. Validation accuracy was misleading - If validation set       
  had same imbalance, 90%+ accuracy means nothing

  Recommended Next Steps (Priority Order)

  1. Fix Class Balance First (Most Important)

  Before adding more data or changing hyperparameters:

  | Option              | Approach
              | Effort           |
  |---------------------|-------------------------------------    
  ------------|------------------|
  | A. Undersample ads  | Use 2K ads + 2K non-ads (4K total)      
              | Easy, fast       |
  | B. Get more non-ads | Download ImageNet/COCO samples, web     
  screenshots | Medium           |
  | C. Weighted loss    | Increase loss weight for non-ad
  class by 39x    | Easy code change |

  I recommend Option A first - quick experiment to validate       
  the hypothesis. If 4K balanced data improves precision
  significantly, then invest in getting more non-ads.

  2. Get More Non-Ad Data (If Option A confirms the issue)        

  Good sources for non-ad images:
  - ImageNet subsets - General objects, scenes
  - COCO dataset - Real-world images
  - Web screenshots - Navigation elements, content (like your     
  existing 2K)
  - Stock photo sites - Diverse content

  Target: At least 1:1 ratio, ideally 50K ads : 50K non-ads       

  3. Hyperparameter Changes (After fixing balance)

  Current settings are reasonable, but:

  | Parameter         | Current | Suggestion
                   |
  |-------------------|---------|-----------------------------    
  -----------------|
  | Epochs (Percival) | 10      | Try 15-20 with early
  stopping                |
  | Epochs (CLIP)     | 5       | Try 10 with early stopping      
                   |
  | Learning rate     | Default | Try lower (1e-4 → 5e-5) for     
  less overfitting |
  | Batch size        | 32/64   | Fine as-is
                   |

  4. More Ad Data? (Lower Priority)

  You already have 78K ads - that's plenty. The bottleneck is     
  non-ads, not ads. Adding 100K more ads would make the
  imbalance worse.

  Quick Experiment I'd Suggest

  # Create balanced subset (2K each)
  # Then retrain Percival with balanced data
  python finetune_percival.py --epochs 15 --batch_size 32
  --balanced

  # Compare precision on same test sets

  Would you like me to:
  1. Modify the training scripts to add class balancing
  (weighted loss or undersampling)?
  2. Help find/download more non-ad data sources?
  3. Create a balanced subset from your existing data for a       
  quick test?

  The class imbalance is almost certainly why you're seeing
  100% recall but only 54-67% precision. Fix that first before    
   anything else.
