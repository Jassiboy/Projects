package Demo.Main.Entity;

import Demo.Main.Resources;

import java.awt.*;

/**
 * Created by jassiboy on 3/5/2017.
 */
public class Dragon extends Entity {

    private Image[] dragonImages = {
            Resources.dragonImage1,
            Resources.dragonImage2,
            Resources.dragonImage3,
            Resources.dragonImage4,
           // Resources.dragonImage4,
            Resources.dragonImage3,
            Resources.dragonImage2,
    };
    private int currentImageIndex = 0;
    private int attackForFrames = 0;
    public boolean isattacked = false;

    public void attack(boolean newIsAttacked) {
        this.isattacked = newIsAttacked;

        if(newIsAttacked) {
            this.rect.setSize(138, 93);
        } else {
            this.rect.setSize(138, 100);
            this.attackForFrames = 0;
        }
    }
    public Dragon(int xCord, int yCord) {
        super(xCord, yCord, 138, 100);
    }
    @Override
    public void update() {
        super.update();

        if(this.isattacked) {
            attackForFrames++;

            if(attackForFrames == 10) {
                this.attack(false);
            }
        } else {
            currentImageIndex++;
            currentImageIndex %= 6;
        }
    }
    @Override
    public Image getImage() {
        if(this.isattacked) {
            return Resources.dragonattack;
           // return Resources.firebollImage;
        } else  {
            return dragonImages[currentImageIndex];
        }
    }
}
